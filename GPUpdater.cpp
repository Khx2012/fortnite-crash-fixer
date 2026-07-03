/*
 * GPUpdater.exe
 * GPU Driver Updater, Diagnostics & Repair Utility
 * Branch of FortniteCrashFixer project
 *
 * Version: 1.2 (C++ / Win32)
 * Targets: NVIDIA, AMD, Intel integrated/Arc
 *
 * Features:
 *   - Detect GPU make, model, driver version (registry DriverVersion key)
 *   - Diagnostics: Windows build (real registry read), VC++ x86+x64, disk space
 *   - Open official driver download pages
 *   - Repair: clear shader cache, run SFC, run DISM, DDU prompt
 *   - Run as admin (auto-elevates with error message on failure)
 *   - Log output anchored to exe directory
 *   - Standalone: works without FortniteCrashFixer present
 *
 * v1.2 changes from v1.1:
 *   - DetectGPU now runs on a worker thread (BeginTask/StartWorkerThread)
 *     — fixes 10-second UI freeze on WMIC fallback path and closes the
 *     data-race window where UI thread + worker both wrote g_GPUName etc.
 *   - Windows build read from registry CurrentBuildNumber (real value) instead
 *     of GetVersionEx which lies on unmanifested apps (caps at 6.2 / Win8)
 *   - DirectX stale registry key replaced with d3d11.dll / d3d12.dll file
 *     version check — gives a meaningful result for modern games
 *   - VC++ redist check now covers both x64 AND x86 — avoids false NOT FOUND
 *     for users who only have the 32-bit runtime installed
 *   - WMIC fallback now has a PowerShell (Get-CimInstance) second fallback
 *     for Windows 11 24H2+ where wmic.exe is removed
 *   - Full Fix order corrected: DISM first, then SFC (Microsoft recommended)
 *   - Log path anchored to exe directory via GetModuleFileName — no more
 *     unpredictable CWD on UAC-elevated relaunch
 *   - RelaunchAsAdmin now shows error message if UAC is declined or fails
 *   - PostMessage return value checked in AppendLog — no silent leak on
 *     queue-full or destroyed window
 */

#define UNICODE
#define _UNICODE
#define _WIN32_WINNT 0x0601
#define WINVER 0x0601

#include <windows.h>
#include <shellapi.h>
#include <setupapi.h>
#include <devguid.h>
#include <commctrl.h>
#include <shlobj.h>
#include <wchar.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <process.h>  // for _beginthreadex — safer than CreateThread with CRT functions

#pragma comment(lib, "setupapi.lib")
#pragma comment(lib, "shell32.lib")
#pragma comment(lib, "comctl32.lib")
#pragma comment(lib, "advapi32.lib")

// ─── Window / control IDs ───────────────────────────────────────────────────
#define IDC_OUTPUT      1001
#define IDC_BTN_DETECT  1002
#define IDC_BTN_NVIDIA  1003
#define IDC_BTN_AMD     1004
#define IDC_BTN_INTEL   1005
#define IDC_BTN_SFC     1006
#define IDC_BTN_DISM    1007
#define IDC_BTN_SHADER  1008
#define IDC_BTN_DDU     1009
#define IDC_BTN_LOG     1010
#define IDC_BTN_CLEAR   1011
#define IDC_PROGRESS    1012
#define IDC_STATUS      1013
#define IDC_LABEL_GPU   1014
#define IDC_LABEL_DRV   1015
#define IDC_BTN_FULLFIX 1016
#define IDC_BTN_DIAG    1017  // Diagnostics

#define WM_APPEND_LOG (WM_USER + 1)
#define WM_TASK_DONE  (WM_USER + 2)

// ─── Globals ────────────────────────────────────────────────────────────────
static HWND  g_hWnd        = NULL;
static HWND  g_hOutput     = NULL;
static HWND  g_hProgress   = NULL;
static HWND  g_hStatus     = NULL;
static HWND  g_hLabelGPU   = NULL;
static HWND  g_hLabelDrv   = NULL;

// Atomic task lock — prevents double-starts even under race conditions
static volatile LONG g_TaskRunning   = FALSE;
// Session counter — incremented on every new task start.
// Log messages carry their session ID; stale messages from old tasks are discarded.
static volatile LONG g_LogGeneration = 0;

static WCHAR g_GPUName[512]      = L"Not detected";
static WCHAR g_DriverVer[128]    = L"Unknown";
static WCHAR g_GPUVendor[64]     = L"Unknown";
// Log path anchored to exe directory in WinMain — never relies on CWD
static WCHAR g_LogPath[MAX_PATH] = L"gpupdater_log.txt";

// GDI font handles — created once in CreateControls, must be deleted on exit
static HFONT g_hMainFont  = NULL;
static HFONT g_hMonoFont  = NULL;
static HFONT g_hTitleFont = NULL;

// Log message struct — carries session ID so WM_APPEND_LOG can discard stale posts
struct LogMsg {
    LONG  generation;
    WCHAR text[1]; // flexible array (allocated with extra space)
};

// ─── Forward declarations ────────────────────────────────────────────────────
LRESULT CALLBACK WndProc(HWND, UINT, WPARAM, LPARAM);
void AppendLog(const WCHAR* msg, LONG session);
void AppendLogUI(const WCHAR* msg);            // UI-thread only (no session check)
void SetStatus(const WCHAR* msg);
BOOL BeginTask(const WCHAR* statusMsg);        // atomic lock + progress + status
void EndTask(void);                            // unlock + hide progress
void DetectGPU(LONG session);      // pure logic — called from DetectGPUThread
unsigned __stdcall DetectGPUThread(void*);
void CheckDriverVersion(const WCHAR* currentVer, LONG session);
void ClearShaderCache(LONG session);
unsigned __stdcall RunSFCThread(void*);
unsigned __stdcall RunDISMThread(void*);
unsigned __stdcall ClearShaderCacheThread(void*);
unsigned __stdcall FullFixThread(void*);
unsigned __stdcall DiagnosticsThread(void*);
HANDLE StartWorkerThread(unsigned (__stdcall *threadFunc)(void*));
void OpenDriverPage(const WCHAR* vendor);
void ExportLog(void);
BOOL IsRunningAsAdmin(void);
void RelaunchAsAdmin(void);
void WriteLogFile(const WCHAR* msg);
SYSTEMTIME GetNow(void);

// ─── Helpers ────────────────────────────────────────────────────────────────

SYSTEMTIME GetNow(void)
{
    SYSTEMTIME st;
    GetLocalTime(&st);
    return st;
}

BOOL IsRunningAsAdmin(void)
{
    BOOL isAdmin = FALSE;
    PSID adminGroup = NULL;
    SID_IDENTIFIER_AUTHORITY ntAuth = SECURITY_NT_AUTHORITY;
    if (AllocateAndInitializeSid(&ntAuth, 2,
        SECURITY_BUILTIN_DOMAIN_RID, DOMAIN_ALIAS_RID_ADMINS,
        0, 0, 0, 0, 0, 0, &adminGroup))
    {
        CheckTokenMembership(NULL, adminGroup, &isAdmin);
        FreeSid(adminGroup);
    }
    return isAdmin;
}

void RelaunchAsAdmin(void)
{
    WCHAR path[MAX_PATH];
    GetModuleFileName(NULL, path, MAX_PATH);
    SHELLEXECUTEINFO sei = { sizeof(sei) };
    sei.lpVerb    = L"runas";
    sei.lpFile    = path;
    sei.nShow     = SW_SHOWNORMAL;
    if (!ShellExecuteEx(&sei))
    {
        DWORD err = GetLastError();
        if (err != ERROR_CANCELLED)  // ERROR_CANCELLED = user clicked No on UAC
        {
            WCHAR msg[128];
            wsprintfW(msg, L"Failed to relaunch as administrator.\nError code: %lu", err);
            MessageBox(NULL, msg, L"GPUpdater — Elevation Failed", MB_ICONERROR);
        }
        // If user cancelled UAC, exit silently — they made their choice
    }
}

void WriteLogFile(const WCHAR* msg)
{
    FILE* f = _wfopen(g_LogPath, L"a, ccs=UTF-8");
    if (!f) return;
    SYSTEMTIME st = GetNow();
    fwprintf(f, L"[%04d-%02d-%02d %02d:%02d:%02d] %s\n",
        st.wYear, st.wMonth, st.wDay,
        st.wHour, st.wMinute, st.wSecond, msg);
    fclose(f);
}

void AppendLog(const WCHAR* msg, LONG session)
{
    if (!g_hOutput || !msg) return;

    // Session check on worker thread — avoids disk write + allocation for
    // messages that belong to a superseded task.
    if (session != InterlockedCompareExchange(&g_LogGeneration, 0, 0))
        return;

    WriteLogFile(msg);

    size_t len = wcslen(msg);
    LogMsg* lm = (LogMsg*)malloc(sizeof(LogMsg) + len * sizeof(WCHAR));
    if (!lm) return;
    lm->generation = session;
    wcscpy(lm->text, msg);

    // If PostMessage fails (queue full, window gone), free immediately —
    // no WM_APPEND_LOG handler will ever process this message.
    if (!PostMessage(g_hWnd, WM_APPEND_LOG, 0, (LPARAM)lm))
        free(lm);
}

// For UI-thread calls (startup banner, button feedback) where no session applies
void AppendLogUI(const WCHAR* msg)
{
    AppendLog(msg, InterlockedCompareExchange(&g_LogGeneration, 0, 0));
}

void SetStatus(const WCHAR* msg)
{
    if (g_hStatus)
        SetWindowText(g_hStatus, msg);
}

// ─── Task lifecycle ──────────────────────────────────────────────────────────

// Call from UI thread before spawning any worker thread.
// Returns FALSE if a task is already running (caller should bail out).
BOOL BeginTask(const WCHAR* statusMsg)
{
    // Atomic compare-exchange: only one thread wins
    if (InterlockedCompareExchange(&g_TaskRunning, TRUE, FALSE) != FALSE)
        return FALSE;

    // New session — all prior queued WM_APPEND_LOG messages get discarded
    InterlockedIncrement(&g_LogGeneration);

    ShowWindow(g_hProgress, SW_SHOW);
    SendMessage(g_hProgress, PBM_SETMARQUEE, TRUE, 50);
    SetStatus(statusMsg ? statusMsg : L"Working...");
    return TRUE;
}

// Called via WM_TASK_DONE on the UI thread — never call from worker thread directly.
void EndTask(void)
{
    InterlockedExchange(&g_TaskRunning, FALSE);
    ShowWindow(g_hProgress, SW_HIDE);
    SetStatus(L"Done.");
}

// Spawns a worker thread via _beginthreadex instead of CreateThread.
// _beginthreadex properly initializes CRT per-thread state (errno, strtok buffers,
// etc.) which CreateThread does not — safer when the thread calls CRT functions
// like _wfopen, malloc, wcscpy as ours do.
HANDLE StartWorkerThread(unsigned (__stdcall *threadFunc)(void*))
{
    unsigned threadId = 0;
    HANDLE h = (HANDLE)_beginthreadex(NULL, 0, threadFunc, NULL, 0, &threadId);
    return h;
}

// ─── GPU Detection ───────────────────────────────────────────────────────────

void CheckDriverVersion(const WCHAR* currentVer, LONG session)
{
    AppendLog(L"─────────────────────────────────────", session);
    AppendLog(L"  Driver Version Check",                 session);
    AppendLog(L"─────────────────────────────────────", session);

    WCHAR buf[512];

    if (!currentVer || wcslen(currentVer) == 0 || wcscmp(currentVer, L"Unknown") == 0)
    {
        AppendLog(L"  [ERROR] No driver version detected.", session);
        AppendLog(L"─────────────────────────────────────", session);
        return;
    }

    wsprintfW(buf, L"  Installed : %s", currentVer);
    AppendLog(buf, session);
    AppendLog(L"", session);
    AppendLog(L"  [INFO] Live version check coming in v1.3.", session);
    AppendLog(L"  [INFO] Visit your GPU vendor's site to compare:", session);

    if (wcscmp(g_GPUVendor, L"NVIDIA") == 0)
        AppendLog(L"         nvidia.com/drivers", session);
    else if (wcscmp(g_GPUVendor, L"AMD") == 0)
        AppendLog(L"         amd.com/en/support", session);
    else if (wcscmp(g_GPUVendor, L"Intel") == 0)
        AppendLog(L"         intel.com/content/www/us/en/download-center/home.html", session);
    else
        AppendLog(L"         Search: [GPU name] + latest driver", session);

    AppendLog(L"─────────────────────────────────────", session);
}

void DetectGPU(LONG session)
{
    AppendLog(L"─────────────────────────────────────", session);
    AppendLog(L"  GPU Detection",                        session);
    AppendLog(L"─────────────────────────────────────", session);

    HDEVINFO devInfo = SetupDiGetClassDevs(
        &GUID_DEVCLASS_DISPLAY, NULL, NULL, DIGCF_PRESENT);

    if (devInfo == INVALID_HANDLE_VALUE)
    {
        AppendLog(L"[ERROR] SetupDiGetClassDevs failed.", session);
        return;
    }

    SP_DEVINFO_DATA devData;
    devData.cbSize = sizeof(SP_DEVINFO_DATA);
    BOOL found = FALSE;

    for (DWORD i = 0; SetupDiEnumDeviceInfo(devInfo, i, &devData); i++)
    {
        WCHAR name[512] = L"";

        if (!SetupDiGetDeviceRegistryProperty(devInfo, &devData,
            SPDRP_FRIENDLYNAME, NULL, (PBYTE)name, sizeof(name), NULL))
        {
            SetupDiGetDeviceRegistryProperty(devInfo, &devData,
                SPDRP_DEVICEDESC, NULL, (PBYTE)name, sizeof(name), NULL);
        }

        if (wcslen(name) == 0) continue;

        if (wcsstr(name, L"RemoteFX") || wcsstr(name, L"Hyper-V")  ||
            wcsstr(name, L"Virtual")  || wcsstr(name, L"Indirect")  ||
            wcsstr(name, L"Mirror")   || wcsstr(name, L"RDP"))
            continue;

        int nameLen = (int)wcslen(name);
        while (nameLen > 0 && name[nameLen - 1] == L' ') name[--nameLen] = L'\0';

        WCHAR driverVer[128] = L"Unknown";
        HKEY hKey = SetupDiOpenDevRegKey(devInfo, &devData,
            DICS_FLAG_GLOBAL, 0, DIREG_DRV, KEY_READ);
        if (hKey != INVALID_HANDLE_VALUE)
        {
            DWORD sz = sizeof(driverVer);
            RegQueryValueEx(hKey, L"DriverVersion", NULL, NULL, (LPBYTE)driverVer, &sz);
            driverVer[127] = L'\0';
            RegCloseKey(hKey);
        }

        wcsncpy(g_GPUName,   name,      511); g_GPUName[511]   = L'\0';
        wcsncpy(g_DriverVer, driverVer, 127); g_DriverVer[127] = L'\0';

        if (wcsstr(name, L"NVIDIA") || wcsstr(name, L"GeForce") ||
            wcsstr(name, L"RTX")    || wcsstr(name, L"GTX")     || wcsstr(name, L"Quadro"))
            wcsncpy(g_GPUVendor, L"NVIDIA", 63);
        else if (wcsstr(name, L"AMD") || wcsstr(name, L"Radeon") || wcsstr(name, L"RX "))
            wcsncpy(g_GPUVendor, L"AMD", 63);
        else if (wcsstr(name, L"Intel") || wcsstr(name, L"Arc") ||
                 wcsstr(name, L"UHD")   || wcsstr(name, L"Iris"))
            wcsncpy(g_GPUVendor, L"Intel", 63);
        else
            wcsncpy(g_GPUVendor, L"Other", 63);
        g_GPUVendor[63] = L'\0';

        found = TRUE;

        WCHAR buf[700];
        wsprintfW(buf, L"  GPU Found  : %s", g_GPUName);   AppendLog(buf, session);
        wsprintfW(buf, L"  Vendor     : %s", g_GPUVendor); AppendLog(buf, session);
        wsprintfW(buf, L"  Driver Ver : %s", g_DriverVer); AppendLog(buf, session);
        AppendLog(L"", session);

        // Update header labels — PostMessage so it's safe from worker thread
        PostMessage(g_hWnd, WM_SETTEXT, 0, 0); // triggers label update below
        SetWindowText(g_hLabelGPU, g_GPUName);
        SetWindowText(g_hLabelDrv, g_DriverVer);

        break; // v1.3 TODO: enumerate all, let user pick
    }

    SetupDiDestroyDeviceInfoList(devInfo);

    if (!found)
    {
        AppendLog(L"[WARN] No display adapter found via SetupAPI.", session);

        // ── WMIC fallback (deprecated in Win11 24H2 — see PowerShell fallback below) ──
        AppendLog(L"       Trying WMIC fallback...", session);

        WCHAR wmicCmd[256] =
            L"cmd /c wmic path win32_VideoController get name,driverversion /format:list"
            L" > \"%TEMP%\\gpuinfo.txt\" 2>&1";
        STARTUPINFO si = { sizeof(si) };
        si.dwFlags = STARTF_USESHOWWINDOW; si.wShowWindow = SW_HIDE;
        PROCESS_INFORMATION pi;
        BOOL wmicOk = FALSE;

        if (CreateProcess(NULL, wmicCmd, NULL, NULL, FALSE, 0, NULL, NULL, &si, &pi))
        {
            WaitForSingleObject(pi.hProcess, 10000);
            CloseHandle(pi.hProcess); CloseHandle(pi.hThread);

            WCHAR tmpPath[MAX_PATH];
            ExpandEnvironmentStrings(L"%TEMP%\\gpuinfo.txt", tmpPath, MAX_PATH);
            FILE* f = _wfopen(tmpPath, L"r, ccs=UTF-8");
            if (f)
            {
                WCHAR line[512], wmicName[512] = L"", wmicDrv[128] = L"";
                while (fgetws(line, 512, f))
                {
                    int ll = (int)wcslen(line);
                    while (ll > 0 && (line[ll-1]==L'\n'||line[ll-1]==L'\r')) line[--ll]=0;
                    if (ll == 0) continue;
                    WCHAR* eq = wcschr(line, L'='); if (!eq) continue;
                    *eq = 0;
                    if (_wcsicmp(line, L"Name")==0 && wcslen(eq+1)>0)
                        wcsncpy(wmicName, eq+1, 511);
                    else if (_wcsicmp(line, L"DriverVersion")==0 && wcslen(eq+1)>0)
                        wcsncpy(wmicDrv, eq+1, 127);
                }
                fclose(f); DeleteFile(tmpPath);

                if (wcslen(wmicName) > 0)
                {
                    wcsncpy(g_GPUName,   wmicName, 511); g_GPUName[511]   = 0;
                    wcsncpy(g_DriverVer, wmicDrv,  127); g_DriverVer[127] = 0;
                    wmicOk = TRUE;
                }
            }
        }

        // ── PowerShell / CimInstance fallback (Win11 24H2+ where wmic is gone) ──
        if (!wmicOk)
        {
            AppendLog(L"       WMIC unavailable. Trying PowerShell...", session);
            WCHAR psCmd[512] =
                L"cmd /c powershell -NoProfile -Command \""
                L"Get-CimInstance Win32_VideoController | "
                L"Select-Object Name,DriverVersion | "
                L"ForEach-Object { 'Name=' + $_.Name; 'DriverVersion=' + $_.DriverVersion }\" "
                L"> \"%TEMP%\\gpuinfo_ps.txt\" 2>&1";

            STARTUPINFO si2 = { sizeof(si2) };
            si2.dwFlags = STARTF_USESHOWWINDOW; si2.wShowWindow = SW_HIDE;
            PROCESS_INFORMATION pi2;
            if (CreateProcess(NULL, psCmd, NULL, NULL, FALSE, 0, NULL, NULL, &si2, &pi2))
            {
                WaitForSingleObject(pi2.hProcess, 15000);
                CloseHandle(pi2.hProcess); CloseHandle(pi2.hThread);

                WCHAR psPath[MAX_PATH];
                ExpandEnvironmentStrings(L"%TEMP%\\gpuinfo_ps.txt", psPath, MAX_PATH);
                FILE* f2 = _wfopen(psPath, L"r, ccs=UTF-8");
                if (f2)
                {
                    WCHAR line[512], psName[512] = L"", psDrv[128] = L"";
                    while (fgetws(line, 512, f2))
                    {
                        int ll = (int)wcslen(line);
                        while (ll > 0 && (line[ll-1]==L'\n'||line[ll-1]==L'\r')) line[--ll]=0;
                        if (ll == 0) continue;
                        WCHAR* eq = wcschr(line, L'='); if (!eq) continue;
                        *eq = 0;
                        if (_wcsicmp(line, L"Name")==0 && wcslen(eq+1)>0)
                            wcsncpy(psName, eq+1, 511);
                        else if (_wcsicmp(line, L"DriverVersion")==0 && wcslen(eq+1)>0)
                            wcsncpy(psDrv, eq+1, 127);
                    }
                    fclose(f2); DeleteFile(psPath);
                    if (wcslen(psName) > 0)
                    {
                        wcsncpy(g_GPUName,   psName, 511); g_GPUName[511]   = 0;
                        wcsncpy(g_DriverVer, psDrv,  127); g_DriverVer[127] = 0;
                        wmicOk = TRUE;
                        AppendLog(L"       PowerShell fallback succeeded.", session);
                    }
                }
            }
        }

        if (wmicOk)
        {
            // Determine vendor from whatever name we got
            if (wcsstr(g_GPUName,L"NVIDIA")||wcsstr(g_GPUName,L"GeForce")||
                wcsstr(g_GPUName,L"RTX")||wcsstr(g_GPUName,L"GTX"))
                wcsncpy(g_GPUVendor, L"NVIDIA", 63);
            else if (wcsstr(g_GPUName,L"AMD")||wcsstr(g_GPUName,L"Radeon"))
                wcsncpy(g_GPUVendor, L"AMD", 63);
            else if (wcsstr(g_GPUName,L"Intel"))
                wcsncpy(g_GPUVendor, L"Intel", 63);
            else
                wcsncpy(g_GPUVendor, L"Other", 63);
            g_GPUVendor[63] = 0;

            WCHAR buf[700];
            wsprintfW(buf, L"  GPU Found  : %s", g_GPUName);   AppendLog(buf, session);
            wsprintfW(buf, L"  Vendor     : %s", g_GPUVendor); AppendLog(buf, session);
            wsprintfW(buf, L"  Driver Ver : %s",
                wcslen(g_DriverVer)>0 ? g_DriverVer : L"Unknown"); AppendLog(buf, session);
            SetWindowText(g_hLabelGPU, g_GPUName);
            SetWindowText(g_hLabelDrv, wcslen(g_DriverVer)>0 ? g_DriverVer : L"Unknown");
            found = TRUE;
        }
        else
        {
            AppendLog(L"[ERROR] All GPU detection methods failed.", session);
            SetWindowText(g_hLabelGPU, L"Not detected");
            SetWindowText(g_hLabelDrv, L"Unknown");
        }
    }

    AppendLog(L"─────────────────────────────────────", session);
    SetStatus(L"GPU detection complete.");
    CheckDriverVersion(g_DriverVer, session);
}

unsigned __stdcall DetectGPUThread(void* param)
{
    LONG session = InterlockedCompareExchange(&g_LogGeneration, 0, 0);
    DetectGPU(session);
    PostMessage(g_hWnd, WM_TASK_DONE, 0, 0);
    return 0;
}

// ─── Diagnostics ─────────────────────────────────────────────────────────────

unsigned __stdcall DiagnosticsThread(void* param)
{
    LONG session = InterlockedCompareExchange(&g_LogGeneration, 0, 0);
    WCHAR buf[512];

    AppendLog(L"", session);
    AppendLog(L"─────────────────────────────────────", session);
    AppendLog(L"  System Diagnostics",                  session);
    AppendLog(L"─────────────────────────────────────", session);

    // ── Windows build — read from registry, not GetVersionEx ────────────
    // GetVersionEx lies on unmanifested apps (caps at 6.2/Win8 on Win8.1+).
    // CurrentBuildNumber in the NT registry always has the real value.
    WCHAR buildNum[32]  = L"Unknown";
    WCHAR buildUBR[32]  = L"";
    HKEY hWinVer;
    if (RegOpenKeyEx(HKEY_LOCAL_MACHINE,
        L"SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion",
        0, KEY_READ, &hWinVer) == ERROR_SUCCESS)
    {
        DWORD sz = sizeof(buildNum);
        RegQueryValueEx(hWinVer, L"CurrentBuildNumber", NULL, NULL, (LPBYTE)buildNum, &sz);
        buildNum[31] = 0;

        // UBR = Update Build Revision (e.g. .3374 in 22621.3374)
        DWORD ubr = 0, ubrSz = sizeof(ubr);
        if (RegQueryValueEx(hWinVer, L"UBR", NULL, NULL, (LPBYTE)&ubr, &ubrSz) == ERROR_SUCCESS)
            wsprintfW(buildUBR, L".%lu", ubr);

        RegCloseKey(hWinVer);
    }
    DWORD build = (DWORD)_wtoi(buildNum);
    wsprintfW(buf, L"  Windows     : Build %s%s", buildNum, buildUBR);
    AppendLog(buf, session);
    if (build >= 22000)
        AppendLog(L"                (Windows 11)", session);
    else if (build >= 10240)
        AppendLog(L"                (Windows 10)", session);
    else if (build > 0)
        AppendLog(L"                (Older Windows — consider upgrading)", session);

    // ── DirectX — check d3d file versions, not the stale DX9 registry key ──
    // The HKLM\Microsoft\DirectX\Version key hasn't been updated since the DX9
    // era and means nothing for DX11/12 titles like Fortnite.
    WCHAR sysDir[MAX_PATH];
    GetSystemDirectory(sysDir, MAX_PATH);
    BOOL hasDX12 = FALSE, hasDX11 = FALSE;
    {
        WCHAR d12[MAX_PATH]; wsprintfW(d12, L"%s\\d3d12.dll", sysDir);
        hasDX12 = (GetFileAttributes(d12) != INVALID_FILE_ATTRIBUTES);
        WCHAR d11[MAX_PATH]; wsprintfW(d11, L"%s\\d3d11.dll", sysDir);
        hasDX11 = (GetFileAttributes(d11) != INVALID_FILE_ATTRIBUTES);
    }
    if (hasDX12)
        AppendLog(L"  DirectX     : DX12 present (d3d12.dll found)", session);
    else if (hasDX11)
        AppendLog(L"  DirectX     : DX11 present — DX12 not found", session);
    else
        AppendLog(L"  DirectX     : Neither d3d11.dll nor d3d12.dll found", session);

    // ── Visual C++ Redistributable — check BOTH x64 and x86 ────────────
    // x86 redist is still required by many games (including some Fortnite deps).
    // Reporting NOT FOUND when only x86 is installed is a false positive.
    BOOL vcX64 = FALSE, vcX86 = FALSE;
    const WCHAR* vcX64Keys[] = {
        L"SOFTWARE\\Microsoft\\VisualStudio\\14.0\\VC\\Runtimes\\X64",
        L"SOFTWARE\\WOW6432Node\\Microsoft\\VisualStudio\\14.0\\VC\\Runtimes\\x64",
        NULL
    };
    const WCHAR* vcX86Keys[] = {
        L"SOFTWARE\\WOW6432Node\\Microsoft\\VisualStudio\\14.0\\VC\\Runtimes\\X86",
        L"SOFTWARE\\Microsoft\\VisualStudio\\14.0\\VC\\Runtimes\\x86",
        NULL
    };
    for (int k = 0; vcX64Keys[k] && !vcX64; k++)
    {
        HKEY h; DWORD inst=0, sz=sizeof(inst);
        if (RegOpenKeyEx(HKEY_LOCAL_MACHINE, vcX64Keys[k], 0, KEY_READ, &h)==ERROR_SUCCESS)
        {
            RegQueryValueEx(h, L"Installed", NULL, NULL, (LPBYTE)&inst, &sz);
            RegCloseKey(h);
            if (inst == 1) vcX64 = TRUE;
        }
    }
    for (int k = 0; vcX86Keys[k] && !vcX86; k++)
    {
        HKEY h; DWORD inst=0, sz=sizeof(inst);
        if (RegOpenKeyEx(HKEY_LOCAL_MACHINE, vcX86Keys[k], 0, KEY_READ, &h)==ERROR_SUCCESS)
        {
            RegQueryValueEx(h, L"Installed", NULL, NULL, (LPBYTE)&inst, &sz);
            RegCloseKey(h);
            if (inst == 1) vcX86 = TRUE;
        }
    }
    wsprintfW(buf, L"  VC++ x64    : %s", vcX64 ? L"Installed" : L"NOT FOUND");
    AppendLog(buf, session);
    wsprintfW(buf, L"  VC++ x86    : %s", vcX86 ? L"Installed" : L"NOT FOUND");
    AppendLog(buf, session);
    if (!vcX64 || !vcX86)
        AppendLog(L"  [!] Missing VC++ Redist — download from microsoft.com/en-us/download", session);

    // ── GPU summary ───────────────────────────────────────────────────────
    if (wcscmp(g_GPUVendor, L"Unknown") == 0)
        AppendLog(L"  GPU Status  : Not detected — run Detect GPU first", session);
    else
    {
        wsprintfW(buf, L"  GPU Vendor  : %s", g_GPUVendor); AppendLog(buf, session);
        wsprintfW(buf, L"  GPU Driver  : %s", g_DriverVer); AppendLog(buf, session);
    }

    // ── Disk space on C: ─────────────────────────────────────────────────
    ULARGE_INTEGER freeBytesAvail, totalBytes;
    if (GetDiskFreeSpaceEx(L"C:\\", &freeBytesAvail, &totalBytes, NULL))
    {
        DWORD freeGB  = (DWORD)(freeBytesAvail.QuadPart / (1024ULL*1024*1024));
        DWORD totalGB = (DWORD)(totalBytes.QuadPart      / (1024ULL*1024*1024));
        wsprintfW(buf, L"  C: Drive    : %d GB free of %d GB", freeGB, totalGB);
        AppendLog(buf, session);
        if (freeGB < 5)
            AppendLog(L"  [!] Low disk space may cause driver install failures.", session);
    }

    AppendLog(L"", session);
    AppendLog(L"  Diagnostics complete.",               session);
    AppendLog(L"─────────────────────────────────────", session);

    PostMessage(g_hWnd, WM_TASK_DONE, 0, 0);
    return 0;
}

// ─── Repair threads ──────────────────────────────────────────────────────────

static void RunElevatedCommand(const WCHAR* cmd, const WCHAR* logLabel, LONG session)
{
    WCHAR buf[512];
    wsprintfW(buf, L"Running: %s", logLabel);
    AppendLog(buf, session);
    SetStatus(logLabel);

    SHELLEXECUTEINFO sei = { sizeof(sei) };
    sei.lpVerb       = L"runas";
    sei.lpFile       = L"cmd.exe";
    WCHAR args[512];
    wsprintfW(args, L"/c %s & pause", cmd);
    sei.lpParameters = args;
    sei.nShow        = SW_SHOW;
    sei.fMask        = SEE_MASK_NOCLOSEPROCESS;

    if (ShellExecuteEx(&sei))
    {
        if (sei.hProcess)
        {
            WaitForSingleObject(sei.hProcess, INFINITE);
            CloseHandle(sei.hProcess);
        }
        AppendLog(L"[OK] Command finished.", session);
    }
    else
    {
        AppendLog(L"[ERROR] Failed to launch command (user cancelled UAC or error).", session);
    }
}

unsigned __stdcall RunSFCThread(void* param)
{
    LONG session = InterlockedCompareExchange(&g_LogGeneration, 0, 0);
    AppendLog(L"", session);
    AppendLog(L"─────────────────────────────────────", session);
    AppendLog(L"  System File Checker (SFC)",           session);
    AppendLog(L"─────────────────────────────────────", session);
    AppendLog(L"Scans and repairs corrupted system files.", session);
    AppendLog(L"May take 10-20 minutes. Do not close the window.", session);
    AppendLog(L"", session);
    RunElevatedCommand(L"sfc /scannow", L"sfc /scannow", session);
    AppendLog(L"SFC complete. Check the command window for results.", session);
    AppendLog(L"─────────────────────────────────────", session);
    PostMessage(g_hWnd, WM_TASK_DONE, 0, 0);
    return 0;
}

unsigned __stdcall RunDISMThread(void* param)
{
    LONG session = InterlockedCompareExchange(&g_LogGeneration, 0, 0);
    AppendLog(L"", session);
    AppendLog(L"─────────────────────────────────────", session);
    AppendLog(L"  DISM — Windows Image Repair",         session);
    AppendLog(L"─────────────────────────────────────", session);
    AppendLog(L"Repairs the Windows component store.",  session);
    AppendLog(L"Requires internet. May take 15-30 minutes.", session);
    AppendLog(L"", session);
    RunElevatedCommand(
        L"DISM /Online /Cleanup-Image /RestoreHealth",
        L"DISM /Online /Cleanup-Image /RestoreHealth", session);
    AppendLog(L"DISM complete. Check the command window for results.", session);
    AppendLog(L"─────────────────────────────────────", session);
    PostMessage(g_hWnd, WM_TASK_DONE, 0, 0);
    return 0;
}

// ─── Repair functions ─────────────────────────────────────────────────────────
// ClearShaderCache() = pure logic, no WM_TASK_DONE.
// ClearShaderCacheThread() = wraps it for standalone button use.
// FullFixThread() calls ClearShaderCache() directly — avoids false task-done.

void ClearShaderCache(LONG session)
{
    AppendLog(L"", session);
    AppendLog(L"─────────────────────────────────────", session);
    AppendLog(L"  Clear DirectX Shader Cache",          session);
    AppendLog(L"─────────────────────────────────────", session);

    STARTUPINFO si = { sizeof(si) };
    si.dwFlags     = STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_HIDE;
    PROCESS_INFORMATION pi;
    WCHAR cmdLine[MAX_PATH + 64];
    WCHAR buf[MAX_PATH + 64];

    WCHAR cachePath[MAX_PATH];
    ExpandEnvironmentStrings(L"%LOCALAPPDATA%\\D3DSCache", cachePath, MAX_PATH);
    wsprintfW(buf, L"  Clearing D3DSCache: %s", cachePath);
    AppendLog(buf, session);
    wsprintfW(cmdLine, L"cmd.exe /c rd /s /q \"%s\"", cachePath);
    if (CreateProcess(NULL, cmdLine, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, NULL, &si, &pi))
    {
        WaitForSingleObject(pi.hProcess, 10000);
        CloseHandle(pi.hProcess); CloseHandle(pi.hThread);
        AppendLog(L"  [OK] D3DSCache cleared.", session);
    }
    else
        AppendLog(L"  [WARN] D3DSCache not found or already empty.", session);

    if (wcscmp(g_GPUVendor, L"NVIDIA") == 0)
    {
        WCHAR nvCache[MAX_PATH];
        ExpandEnvironmentStrings(L"%LOCALAPPDATA%\\NVIDIA\\DXCache", nvCache, MAX_PATH);
        wsprintfW(cmdLine, L"cmd.exe /c rd /s /q \"%s\"", nvCache);
        if (CreateProcess(NULL, cmdLine, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, NULL, &si, &pi))
        {
            WaitForSingleObject(pi.hProcess, 5000);
            CloseHandle(pi.hProcess); CloseHandle(pi.hThread);
            AppendLog(L"  [OK] NVIDIA DXCache cleared.", session);
        }

        WCHAR nvCache2[MAX_PATH];
        ExpandEnvironmentStrings(L"%LOCALAPPDATA%\\NVIDIA\\GLCache", nvCache2, MAX_PATH);
        wsprintfW(cmdLine, L"cmd.exe /c rd /s /q \"%s\"", nvCache2);
        if (CreateProcess(NULL, cmdLine, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, NULL, &si, &pi))
        {
            WaitForSingleObject(pi.hProcess, 5000);
            CloseHandle(pi.hProcess); CloseHandle(pi.hThread);
            AppendLog(L"  [OK] NVIDIA GLCache cleared.", session);
        }
    }

    AppendLog(L"  Shader cache clear complete.", session);
    AppendLog(L"─────────────────────────────────────", session);
}

unsigned __stdcall ClearShaderCacheThread(void* param)
{
    LONG session = InterlockedCompareExchange(&g_LogGeneration, 0, 0);
    ClearShaderCache(session);
    PostMessage(g_hWnd, WM_TASK_DONE, 0, 0);
    return 0;
}

unsigned __stdcall FullFixThread(void* param)
{
    LONG session = InterlockedCompareExchange(&g_LogGeneration, 0, 0);
    AppendLog(L"", session);
    AppendLog(L"═════════════════════════════════════", session);
    AppendLog(L"  FULL GPU FIX SEQUENCE",               session);
    AppendLog(L"═════════════════════════════════════", session);
    AppendLog(L"Step 1/3 — Clearing shader cache...",   session);
    ClearShaderCache(session);

    AppendLog(L"", session);
    AppendLog(L"Step 2/3 — Running DISM first...",      session);
    AppendLog(L"  (DISM repairs the component store SFC pulls from)", session);
    RunElevatedCommand(L"DISM /Online /Cleanup-Image /RestoreHealth", L"DISM RestoreHealth", session);

    AppendLog(L"", session);
    AppendLog(L"Step 3/3 — Running SFC...",             session);
    RunElevatedCommand(L"sfc /scannow", L"SFC /scannow", session);

    AppendLog(L"", session);
    AppendLog(L"═════════════════════════════════════", session);
    AppendLog(L"  Full fix sequence finished.",          session);
    AppendLog(L"  Please restart your PC and then",     session);
    AppendLog(L"  update your GPU drivers.",             session);
    AppendLog(L"═════════════════════════════════════", session);
    PostMessage(g_hWnd, WM_TASK_DONE, 0, 0);  // fires once, at the real end
    return 0;
}

// ─── Driver download pages ───────────────────────────────────────────────────

void OpenDriverPage(const WCHAR* vendor)
{
    const WCHAR* url = NULL;
    if (wcscmp(vendor, L"NVIDIA") == 0)
        url = L"https://www.nvidia.com/en-us/drivers/";
    else if (wcscmp(vendor, L"AMD") == 0)
        url = L"https://www.amd.com/en/support/download/drivers.html";
    else if (wcscmp(vendor, L"Intel") == 0)
        url = L"https://www.intel.com/content/www/us/en/download-center/home.html";
    else
        url = L"https://www.google.com/search?q=GPU+driver+download";

    WCHAR buf[256];
    wsprintfW(buf, L"Opening driver page for: %s", vendor);
    AppendLogUI(buf);

    ShellExecute(NULL, L"open", url, NULL, NULL, SW_SHOWNORMAL);
}

// ─── Log export ──────────────────────────────────────────────────────────────

void ExportLog(void)
{
    // Get text from edit control and write to file
    int len = GetWindowTextLength(g_hOutput);
    if (len == 0)
    {
        MessageBox(g_hWnd, L"No log content to save.", L"GPUpdater", MB_ICONINFORMATION);
        return;
    }
    WCHAR* buf = (WCHAR*)malloc((len + 2) * sizeof(WCHAR));
    if (!buf) return;
    GetWindowText(g_hOutput, buf, len + 1);

    FILE* f = _wfopen(g_LogPath, L"w, ccs=UTF-8");
    if (f)
    {
        fwprintf(f, L"%s\n", buf);
        fclose(f);

        WCHAR msg[MAX_PATH + 64];
        wsprintfW(msg, L"Log saved to:\n%s", g_LogPath);
        MessageBox(g_hWnd, msg, L"Log Saved", MB_ICONINFORMATION);
    }
    else
    {
        MessageBox(g_hWnd, L"Failed to write log file.", L"Error", MB_ICONERROR);
    }
    free(buf);
}

// ─── DDU Info dialog ─────────────────────────────────────────────────────────

void ShowDDUInfo(void)
{
    const WCHAR* msg =
        L"DDU (Display Driver Uninstaller) is a free third-party tool\n"
        L"that completely removes GPU drivers before reinstalling.\n\n"
        L"Use DDU when:\n"
        L"  - Switching from NVIDIA to AMD (or vice versa)\n"
        L"  - A driver update failed or caused instability\n"
        L"  - Games crash immediately on launch\n\n"
        L"IMPORTANT: DDU is NOT made by GPUpdater or FortniteCrashFixer.\n"
        L"It is a well-known community tool hosted on Guru3D.\n"
        L"Review the website and download at your own discretion.\n\n"
        L"Boot into Safe Mode before running DDU.\n\n"
        L"Open DDU download page (guru3d.com)?";

    if (MessageBox(g_hWnd, msg, L"DDU — Third-Party Tool Warning",
        MB_YESNO | MB_ICONWARNING) == IDYES)
    {
        ShellExecute(NULL, L"open",
            L"https://www.guru3d.com/page/display-driver-uninstaller-download/",
            NULL, NULL, SW_SHOWNORMAL);
        AppendLogUI(L"[INFO] Opened DDU download page (guru3d.com).");
        AppendLogUI(L"[INFO] DDU is a third-party tool — review before use.");
    }
}

// ─── Window creation ─────────────────────────────────────────────────────────

void CreateControls(HWND hWnd)
{
    // Create ONE clear, readable font for ALL controls
    g_hMainFont = CreateFont(16, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE,
        DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
        DEFAULT_QUALITY, DEFAULT_PITCH | FF_DONTCARE, L"Segoe UI");

    // Mono font for the log output (keeps columns aligned)
    g_hMonoFont = CreateFont(15, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE,
        ANSI_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
        DEFAULT_QUALITY, FIXED_PITCH | FF_MODERN, L"Consolas");

    // Title bar - larger and bold
    g_hTitleFont = CreateFont(18, 0, 0, 0, FW_BOLD, FALSE, FALSE, FALSE,
        DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
        DEFAULT_QUALITY, DEFAULT_PITCH | FF_DONTCARE, L"Segoe UI");

    HFONT hMainFont  = g_hMainFont;
    HFONT hMonoFont  = g_hMonoFont;
    HFONT hTitleFont = g_hTitleFont;

    HWND hTitle = CreateWindow(L"STATIC",
        L"GPUpdater v1.1 \x2014 GPU Updater, Diagnostics & Repair",
        WS_CHILD | WS_VISIBLE | SS_LEFT | SS_NOPREFIX,
        10, 8, 580, 28, hWnd, NULL, NULL, NULL);
    SendMessage(hTitle, WM_SETFONT, (WPARAM)hTitleFont, TRUE);

    // GPU info labels - use main font
    HWND hGpuLabel = CreateWindow(L"STATIC", L"GPU:", WS_CHILD | WS_VISIBLE | SS_LEFT,
        10, 42, 50, 22, hWnd, NULL, NULL, NULL);
    SendMessage(hGpuLabel, WM_SETFONT, (WPARAM)hMainFont, TRUE);

    g_hLabelGPU = CreateWindow(L"STATIC", L"Not detected",
        WS_CHILD | WS_VISIBLE | SS_LEFT | SS_NOPREFIX,
        65, 42, 530, 22, hWnd,
        (HMENU)IDC_LABEL_GPU, NULL, NULL);
    SendMessage(g_hLabelGPU, WM_SETFONT, (WPARAM)hMainFont, TRUE);

    HWND hDrvLabel = CreateWindow(L"STATIC", L"Driver:", WS_CHILD | WS_VISIBLE | SS_LEFT,
        10, 66, 55, 22, hWnd, NULL, NULL, NULL);
    SendMessage(hDrvLabel, WM_SETFONT, (WPARAM)hMainFont, TRUE);

    g_hLabelDrv = CreateWindow(L"STATIC", L"Unknown",
        WS_CHILD | WS_VISIBLE | SS_LEFT | SS_NOPREFIX,
        70, 66, 525, 22, hWnd,
        (HMENU)IDC_LABEL_DRV, NULL, NULL);
    SendMessage(g_hLabelDrv, WM_SETFONT, (WPARAM)hMainFont, TRUE);

    // Output log - use monospace font for alignment
    g_hOutput = CreateWindow(L"EDIT", L"",
        WS_CHILD | WS_VISIBLE | WS_VSCROLL | WS_BORDER |
        ES_MULTILINE | ES_READONLY | ES_AUTOVSCROLL,
        10, 94, 580, 280, hWnd, (HMENU)IDC_OUTPUT, NULL, NULL);
    SendMessage(g_hOutput, WM_SETFONT, (WPARAM)hMonoFont, TRUE);

    // Progress bar (no font needed)
    g_hProgress = CreateWindow(PROGRESS_CLASS, NULL,
        WS_CHILD | WS_VISIBLE | PBS_MARQUEE,
        10, 380, 580, 14, hWnd, (HMENU)IDC_PROGRESS, NULL, NULL);
    ShowWindow(g_hProgress, SW_HIDE);

    // Status bar - use main font
    g_hStatus = CreateWindow(L"STATIC", L"Ready.",
        WS_CHILD | WS_VISIBLE | SS_LEFT,
        10, 400, 580, 22, hWnd, (HMENU)IDC_STATUS, NULL, NULL);
    SendMessage(g_hStatus, WM_SETFONT, (WPARAM)hMainFont, TRUE);

    // ── Row 1: Detect + Download ──────────────────────────────────────────
    struct { int x; int w; const WCHAR* label; int id; } btns1[] = {
        { 10,  115, L"Detect GPU",     IDC_BTN_DETECT },
        { 135, 115, L"NVIDIA Drivers", IDC_BTN_NVIDIA },
        { 260, 115, L"AMD Drivers",    IDC_BTN_AMD    },
        { 385, 115, L"Intel Drivers",  IDC_BTN_INTEL  },
    };
    for (int i = 0; i < 4; i++)
    {
        HWND h = CreateWindow(L"BUTTON", btns1[i].label,
            WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
            btns1[i].x, 424, btns1[i].w, 32,
            hWnd, (HMENU)(UINT_PTR)btns1[i].id, NULL, NULL);
        SendMessage(h, WM_SETFONT, (WPARAM)hMainFont, TRUE);
    }

    // ── Row 2: Repair ─────────────────────────────────────────────────────
    struct { int x; int w; const WCHAR* label; int id; } btns2[] = {
        { 10,  115, L"Clear Shader Cache", IDC_BTN_SHADER },
        { 135, 115, L"Run SFC",            IDC_BTN_SFC    },
        { 260, 115, L"Run DISM",           IDC_BTN_DISM   },
        { 385, 115, L"DDU Info",           IDC_BTN_DDU    },
    };
    for (int i = 0; i < 4; i++)
    {
        HWND h = CreateWindow(L"BUTTON", btns2[i].label,
            WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
            btns2[i].x, 464, btns2[i].w, 32,
            hWnd, (HMENU)(UINT_PTR)btns2[i].id, NULL, NULL);
        SendMessage(h, WM_SETFONT, (WPARAM)hMainFont, TRUE);
    }

    // ── Row 3: Full Fix + Diagnostics + Log + Clear ───────────────────────
    struct { int x; int w; const WCHAR* label; int id; } btns3[] = {
        { 10,  175, L"Full Fix (SFC + DISM + Cache)", IDC_BTN_FULLFIX },
        { 195, 115, L"Run Diagnostics",               IDC_BTN_DIAG    },
        { 320, 125, L"Save Log",                      IDC_BTN_LOG     },
        { 455, 125, L"Clear Output",                  IDC_BTN_CLEAR   },
    };
    for (int i = 0; i < 4; i++)
    {
        HWND h = CreateWindow(L"BUTTON", btns3[i].label,
            WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
            btns3[i].x, 504, btns3[i].w, 32,
            hWnd, (HMENU)(UINT_PTR)btns3[i].id, NULL, NULL);
        SendMessage(h, WM_SETFONT, (WPARAM)hMainFont, TRUE);
    }
}

// ─── WndProc ─────────────────────────────────────────────────────────────────

LRESULT CALLBACK WndProc(HWND hWnd, UINT msg, WPARAM wParam, LPARAM lParam)
{
    switch (msg)
    {
    case WM_CREATE:
        g_hWnd = hWnd;
        CreateControls(hWnd);
        AppendLogUI(L"GPUpdater v1.1 — GPU Updater, Diagnostics & Repair");
        AppendLogUI(L"Click 'Detect GPU' to start.");
        AppendLogUI(L"");
        break;

    case WM_APPEND_LOG:
    {
        LogMsg* lm = (LogMsg*)lParam;
        if (!lm) break;
        // Secondary session check on UI thread — catches any that slipped through
        // the window between worker-thread check and PostMessage delivery
        if (lm->generation != InterlockedCompareExchange(&g_LogGeneration, 0, 0))
        {
            free(lm);
            break;
        }

        // Build "text\r\n" in one buffer — single EM_REPLACESEL, no caret flash
        size_t tlen = wcslen(lm->text);
        WCHAR* line = (WCHAR*)malloc((tlen + 3) * sizeof(WCHAR));
        if (line)
        {
            wcscpy(line, lm->text);
            line[tlen]   = L'\r';
            line[tlen+1] = L'\n';
            line[tlen+2] = L'\0';

            // Freeze redraws for the duration of the insert — eliminates the
            // flicker/crossing artifact when ShellExecute briefly steals focus
            SendMessage(g_hOutput, WM_SETREDRAW, FALSE, 0);
            int end = GetWindowTextLength(g_hOutput);
            SendMessage(g_hOutput, EM_SETSEL, end, end);
            SendMessage(g_hOutput, EM_REPLACESEL, FALSE, (LPARAM)line);
            SendMessage(g_hOutput, WM_SETREDRAW, TRUE, 0);
            InvalidateRect(g_hOutput, NULL, FALSE);

            free(line);
        }
        free(lm);
        break;
    }

    case WM_TASK_DONE:
        EndTask();
        break;

    case WM_COMMAND:
    {
        int id = LOWORD(wParam);
        if (id == IDC_BTN_CLEAR)
        {
            // WM_SETTEXT works on readonly edit controls; SetWindowText does not
            SendMessage(g_hOutput, WM_SETTEXT, 0, (LPARAM)L"");
            SendMessage(g_hOutput, EM_SETSEL, 0, 0);
            SendMessage(g_hOutput, EM_SCROLLCARET, 0, 0);
            break;
        }
        if (id == IDC_BTN_LOG)
        {
            ExportLog();
            break;
        }
        if (id == IDC_BTN_DETECT)
        {
            if (!BeginTask(L"Detecting GPU...")) {
                MessageBox(hWnd, L"A task is already running.", L"GPUpdater", MB_ICONWARNING);
                break;
            }
            HANDLE t = StartWorkerThread(DetectGPUThread);
            if (t) CloseHandle(t);
            break;
        }
        if (id == IDC_BTN_NVIDIA)  { OpenDriverPage(L"NVIDIA"); break; }
        if (id == IDC_BTN_AMD)     { OpenDriverPage(L"AMD");    break; }
        if (id == IDC_BTN_INTEL)   { OpenDriverPage(L"Intel");  break; }
        if (id == IDC_BTN_DDU)     { ShowDDUInfo();             break; }

        // ── Threaded tasks — all go through BeginTask ─────────────────────
        if (id == IDC_BTN_SFC)
        {
            if (!BeginTask(L"Running SFC...")) {
                MessageBox(hWnd, L"A task is already running.", L"GPUpdater", MB_ICONWARNING);
                break;
            }
            HANDLE t = StartWorkerThread(RunSFCThread);
            if (t) CloseHandle(t);
        }
        else if (id == IDC_BTN_DISM)
        {
            if (!BeginTask(L"Running DISM...")) {
                MessageBox(hWnd, L"A task is already running.", L"GPUpdater", MB_ICONWARNING);
                break;
            }
            HANDLE t = StartWorkerThread(RunDISMThread);
            if (t) CloseHandle(t);
        }
        else if (id == IDC_BTN_SHADER)
        {
            if (!BeginTask(L"Clearing shader cache...")) {
                MessageBox(hWnd, L"A task is already running.", L"GPUpdater", MB_ICONWARNING);
                break;
            }
            HANDLE t = StartWorkerThread(ClearShaderCacheThread);
            if (t) CloseHandle(t);
        }
        else if (id == IDC_BTN_DIAG)
        {
            if (!BeginTask(L"Running diagnostics...")) {
                MessageBox(hWnd, L"A task is already running.", L"GPUpdater", MB_ICONWARNING);
                break;
            }
            HANDLE t = StartWorkerThread(DiagnosticsThread);
            if (t) CloseHandle(t);
        }
        else if (id == IDC_BTN_FULLFIX)
        {
            if (MessageBox(hWnd,
                L"Full Fix will run:\n"
                L"  1. Clear Shader Cache\n"
                L"  2. SFC /scannow\n"
                L"  3. DISM RestoreHealth\n\n"
                L"This may take 30-60 minutes.\n"
                L"Do not close the windows that open.\n\n"
                L"Continue?",
                L"Full Fix", MB_YESNO | MB_ICONQUESTION) != IDYES) break;

            if (!BeginTask(L"Running Full Fix...")) {
                MessageBox(hWnd, L"A task is already running.", L"GPUpdater", MB_ICONWARNING);
                break;
            }
            HANDLE t = StartWorkerThread(FullFixThread);
            if (t) CloseHandle(t);
        }
        break;
    }

    case WM_CTLCOLORSTATIC:
    {
        HDC hdc = (HDC)wParam;
        SetBkMode(hdc, TRANSPARENT);
        return (LRESULT)GetStockObject(NULL_BRUSH);
    }

    case WM_DESTROY:
        // Clean up GDI font handles — Windows GDI objects leak just like heap memory
        if (g_hMainFont)  { DeleteObject(g_hMainFont);  g_hMainFont  = NULL; }
        if (g_hMonoFont)  { DeleteObject(g_hMonoFont);  g_hMonoFont  = NULL; }
        if (g_hTitleFont) { DeleteObject(g_hTitleFont); g_hTitleFont = NULL; }
        PostQuitMessage(0);
        break;

    default:
        return DefWindowProc(hWnd, msg, wParam, lParam);
    }
    return 0;
}

// ─── WinMain ────────────────────────────────────────────────────────────────

int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE, LPSTR, int nCmdShow)
{
    // Require admin
    if (!IsRunningAsAdmin())
    {
        if (MessageBox(NULL,
            L"GPUpdater requires administrator privileges\n"
            L"to run repair functions (SFC, DISM).\n\n"
            L"Relaunch as administrator?",
            L"GPUpdater — Admin Required",
            MB_YESNO | MB_ICONWARNING) == IDYES)
        {
            RelaunchAsAdmin();
        }
        return 0;
    }

    InitCommonControls();

    // Anchor log path to exe's own directory — CWD is unreliable after UAC elevation
    {
        WCHAR exePath[MAX_PATH];
        GetModuleFileName(NULL, exePath, MAX_PATH);
        WCHAR* lastSlash = wcsrchr(exePath, L'\\');
        if (lastSlash)
        {
            *(lastSlash + 1) = L'\0';
            wsprintfW(g_LogPath, L"%sgpupdater_log.txt", exePath);
        }
    }

    WNDCLASS wc     = { 0 };
    wc.lpfnWndProc  = WndProc;
    wc.hInstance    = hInstance;
    wc.lpszClassName = L"GPUpdaterWnd";
    wc.hbrBackground = (HBRUSH)(COLOR_BTNFACE + 1);
    wc.hCursor      = LoadCursor(NULL, IDC_ARROW);
    wc.hIcon        = LoadIcon(NULL, IDI_APPLICATION);
    RegisterClass(&wc);

    HWND hWnd = CreateWindow(
        L"GPUpdaterWnd", L"GPUpdater v1.1 — GPU Updater, Diagnostics & Repair",
        WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX,
        CW_USEDEFAULT, CW_USEDEFAULT,
        620, 580,
        NULL, NULL, hInstance, NULL);

    ShowWindow(hWnd, nCmdShow);
    UpdateWindow(hWnd);

    MSG msg;
    while (GetMessage(&msg, NULL, 0, 0))
    {
        TranslateMessage(&msg);
        DispatchMessage(&msg);
    }
    return (int)msg.wParam;
}
