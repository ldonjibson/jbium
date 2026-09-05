#Requires -Version 5.1
<#
════════════════════════════════════════════════════════════
.SYNOPSIS
    Jbium Launcher for Windows

.DESCRIPTION
    Launches the Jbium browser with all stealth
    patches active. Detects the browser binary and sets up
    the proper environment for undetectable browsing.

.PARAMETER ProxyUrl
    Proxy server URL (http://user:pass@host:port)

.PARAMETER Headless
    Run in headless mode (not recommended for DataDome)

.PARAMETER GeoCountry
    Override GeoIP country code (e.g., "US", "JP", "GB")

.PARAMETER GeoTimezone
    Override timezone (e.g., "America/New_York")

.PARAMETER GeoLanguage  
    Override language (e.g., "en-US", "ja-JP")

.PARAMETER CpuCores
    Override navigator.hardwareConcurrency value

.PARAMETER DeviceMemory
    Override navigator.deviceMemory value

.PARAMETER ScreenWidth
    Override screen width

.PARAMETER ScreenHeight
    Override screen height

.PARAMETER BinaryPath
    Explicit path to jbium.exe (skips auto-detection)

.PARAMETER DebugPort
    Remote debugging port (default: random 9222-9999)

.PARAMETER UserDataDir
    Custom user data directory

.PARAMETER NoSandbox
    Disable sandbox (required for Docker/CI)

.PARAMETER ExtraArgs
    Additional Chrome arguments passed through

.EXAMPLE
    .\jbium.ps1
    # Launch with defaults

.EXAMPLE
    .\jbium.ps1 -ProxyUrl "http://user:pass@proxy:80" -GeoCountry "US"
    # Launch with proxy and US GeoIP

.EXAMPLE
    .\jbium.ps1 -Headless -CpuCores 4 -DeviceMemory 8
    # Launch headless with specific hardware profile

.EXAMPLE
    .\jbium.ps1 -ExtraArgs @("--window-size=1920,1080")
    # Launch with extra Chrome arguments

.NOTES
    Author:  Jbium Project
    Version: 1.0.0
    Requires: PowerShell 5.1+ (built into Windows 10/11)
#>
# ═══════════════════════════════════════════════════════════

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$ProxyUrl,

    [Parameter(Mandatory = $false)]
    [switch]$Headless,

    [Parameter(Mandatory = $false)]
    [ValidatePattern('^[A-Z]{2}$')]
    [string]$GeoCountry,

    [Parameter(Mandatory = $false)]
    [string]$GeoTimezone,

    [Parameter(Mandatory = $false)]
    [string]$GeoLanguage,

    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 128)]
    [int]$CpuCores,

    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 8)]
    [int]$DeviceMemory,

    [Parameter(Mandatory = $false)]
    [int]$ScreenWidth,

    [Parameter(Mandatory = $false)]
    [int]$ScreenHeight,

    [Parameter(Mandatory = $false)]
    [string]$BinaryPath,

    [Parameter(Mandatory = $false)]
    [int]$DebugPort = (Get-Random -Minimum 9222 -Maximum 9999),

    [Parameter(Mandatory = $false)]
    [string]$UserDataDir,

    [Parameter(Mandatory = $false)]
    [switch]$NoSandbox,

    [Parameter(Mandatory = $false)]
    [string[]]$ExtraArgs,

    [Parameter(Mandatory = $false)]
    [switch]$NoLaunch  # Just prepare, don't launch (for driver use)
)

# ═══════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════

$Script:Version = "1.0.0"
$Script:ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Script:ProjectRoot = Split-Path -Parent $Script:ScriptDir

# ═══════════════════════════════════════════════════════════
# Utility Functions
# ═══════════════════════════════════════════════════════════

function Write-Log {
    param([string]$Message, [string]$Color = "Cyan")
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')]" -ForegroundColor DarkGray -NoNewline
    Write-Host " $Message" -ForegroundColor $Color
}

function Write-Success {
    param([string]$Message)
    Write-Log $Message "Green"
}

function Write-Warning2 {
    param([string]$Message)
    Write-Log $Message "Yellow"
}

function Write-Error2 {
    param([string]$Message)
    Write-Log $Message "Red"
}

function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# ═══════════════════════════════════════════════════════════
# Browser Discovery
# ═══════════════════════════════════════════════════════════

function Find-BrowserBinary {
    <#
    .SYNOPSIS
    Searches for the stealth jbium.exe binary across known locations.
    #>
    
    # If explicit path provided, use it
    if ($BinaryPath) {
        if (Test-Path $BinaryPath) {
            return $BinaryPath
        }
        else {
            Write-Error2 "Binary not found at: $BinaryPath"
            throw "Binary not found: $BinaryPath"
        }
    }
    
    # Check environment variable
    $envPath = [Environment]::GetEnvironmentVariable("STEALTH_BROWSER_PATH", "Process")
    if ($envPath -and (Test-Path $envPath)) {
        return $envPath
    }
    
    # Build search paths
    $searchPaths = @(
        # Relative to script
        (Join-Path $Script:ScriptDir "chrome\jbium.exe"),
        (Join-Path $Script:ScriptDir "jbium.exe"),
        (Join-Path $Script:ProjectRoot "chrome\jbium.exe"),
        (Join-Path $Script:ProjectRoot "builds\windows-x64\jbium.exe"),
        (Join-Path $Script:ProjectRoot "chrome\windows\jbium.exe"),
        
        # Standard install locations
        (Join-Path $env:LOCALAPPDATA "Jbium\jbium.exe"),
        (Join-Path $env:APPDATA "Jbium\jbium.exe"),
        (Join-Path $env:APPDATA "Jbium\bin\jbium.exe"),
        "C:\Program Files\Jbium\jbium.exe",
        "C:\Program Files (x86)\Jbium\jbium.exe",
        
        # User home
        (Join-Path $env:USERPROFILE ".jbium\jbium.exe"),
        (Join-Path $env:USERPROFILE "AppData\Local\Jbium\jbium.exe"),
        
        # Development locations
        "C:\jbium\chromium\src\out\Release\jbium.exe",
        "D:\jbium\chromium\src\out\Release\jbium.exe",
        
        # User data directory in Temp
        (Join-Path $env:TEMP "jbium\jbium.exe")
    )
    
    foreach ($path in $searchPaths) {
        if ($path -and (Test-Path $path)) {
            return $path
        }
    }
    
    # Not found
    Write-Error2 "Stealth browser binary not found!"
    Write-Host ""
    Write-Host "  Searched:" -ForegroundColor Gray
    foreach ($path in $searchPaths) {
        Write-Host "    $path" -ForegroundColor DarkGray
    }
    Write-Host ""
    Write-Host "  Solutions:" -ForegroundColor Yellow
    Write-Host "    1. Use -BinaryPath to specify location"
    Write-Host "    2. Set STEALTH_BROWSER_PATH environment variable"
    Write-Host "    3. Run install.py first"
    Write-Host ""
    
    throw "Stealth browser binary not found"
}

# ═══════════════════════════════════════════════════════════
# Font Setup (Windows)
# ═══════════════════════════════════════════════════════════

function Setup-Fonts {
    <#
    .SYNOPSIS
    Windows uses DirectWrite for font rendering.
    System fonts are found automatically.
    For bundled fonts, we register them temporarily.
    #>
    
    $fontDir = Join-Path $Script:ProjectRoot "fonts\windows"
    
    if (-not (Test-Path $fontDir)) {
        $fontDir = Join-Path $Script:ProjectRoot "fonts"
    }
    
    if ((Test-Path $fontDir) -and (Get-ChildItem $fontDir -Filter "*.ttf" -ErrorAction SilentlyContinue)) {
        Write-Log "  Found bundled fonts in: $fontDir"
        
        # On Windows, we can:
        # Option A: Copy fonts to user's temp and use fontconfig (not native)
        # Option B: Register fonts temporarily (requires admin)
        # Option C: Rely on system fonts (simplest, most native)
        
        # For stealth purposes, we prefer Option C (system fonts)
        # because custom font loading is itself a fingerprint signal.
        # The font_filter patch in Chromium handles which fonts to report.
        
        Write-Log "  Using system fonts (DirectWrite) — more natural"
        Write-Log "  Font filtering handled by Chromium patch"
        
        return @{}
    }
    
    # No bundled fonts — system fonts only
    return @{}
}

function Get-InstalledFonts {
    """Get list of installed system fonts"""
    
    $fonts = @()
    
    # System fonts directory
    $systemFonts = "$env:WINDIR\Fonts"
    if (Test-Path $systemFonts) {
        $fonts = Get-ChildItem $systemFonts -Include "*.ttf", "*.otf" -Recurse -ErrorAction SilentlyContinue |
            ForEach-Object { $_.BaseName }
    }
    
    # User fonts
    $userFonts = "$env:LOCALAPPDATA\Microsoft\Windows\Fonts"
    if (Test-Path $userFonts) {
        $userFontsList = Get-ChildItem $userFonts -Include "*.ttf", "*.otf" -ErrorAction SilentlyContinue |
            ForEach-Object { $_.BaseName }
        $fonts += $userFontsList
    }
    
    return $fonts | Sort-Object -Unique
}

# ═══════════════════════════════════════════════════════════
# Environment Variable Setup
# ═══════════════════════════════════════════════════════════

function Set-StealthEnvironment {
    <#
    .SYNOPSIS
    Sets all STEALTH_* environment variables that the
    Chromium patches read via getenv().
    
    .DESCRIPTION
    Each patch checks specific environment variables:
    - STEALTH_CPU_CORES       → navigator.hardwareConcurrency
    - STEALTH_DEVICE_MEMORY   → navigator.deviceMemory
    - STEALTH_PLATFORM        → navigator.platform
    - STEALTH_GEO_*           → GeoIP consistency
    - STEALTH_CANVAS_SEED     → Canvas noise seed
    - STEALTH_WEBGL_SEED      → WebGL noise seed
    - etc.
    #>
    
    $envVars = @{}
    
    # ── Navigator Spoofing (Patch 007) ──
    
    if ($CpuCores) {
        $envVars["STEALTH_CPU_CORES"] = $CpuCores
        Write-Log "  STEALTH_CPU_CORES = $CpuCores"
    }
    else {
        # Default: realistic consumer hardware
        $defaultCores = (Get-CimInstance -ClassName Win32_Processor | 
            Measure-Object -Property NumberOfCores -Sum).Sum
        # Clamp to consumer range (2-16)
        $clampedCores = [Math]::Min([Math]::Max($defaultCores, 4), 12)
        $envVars["STEALTH_CPU_CORES"] = $clampedCores
        Write-Log "  STEALTH_CPU_CORES = $clampedCores (auto)"
    }
    
    if ($DeviceMemory) {
        $envVars["STEALTH_DEVICE_MEMORY"] = [Math]::Min($DeviceMemory, 8)
        Write-Log "  STEALTH_DEVICE_MEMORY = $DeviceMemory"
    }
    else {
        # Default: 8GB (most common consumer device)
        $envVars["STEALTH_DEVICE_MEMORY"] = "8"
        Write-Log "  STEALTH_DEVICE_MEMORY = 8 (auto)"
    }
    
    # Platform is always Win32 on Windows
    $envVars["STEALTH_PLATFORM"] = "Win32"
    Write-Log "  STEALTH_PLATFORM = Win32"
    
    # Touch points (0 for desktop)
    $envVars["STEALTH_MAX_TOUCH_POINTS"] = "0"
    
    # User-Agent Client Hints
    $envVars["STEALTH_UA_PLATFORM"] = "Windows"
    
    # Detect Windows version for UA hint
    $winVersion = [System.Environment]::OSVersion.Version
    $envVars["STEALTH_UA_PLATFORM_VERSION"] = "$($winVersion.Major).$($winVersion.Minor).0"
    
    # ── GeoIP Consistency (Patch 008) ──
    
    if ($GeoCountry) {
        $envVars["STEALTH_GEO_COUNTRY"] = $GeoCountry
        Write-Log "  STEALTH_GEO_COUNTRY = $GeoCountry"
    }
    
    if ($GeoTimezone) {
        $envVars["STEALTH_GEO_TIMEZONE"] = $GeoTimezone
        Write-Log "  STEALTH_GEO_TIMEZONE = $GeoTimezone"
    }
    else {
        # Use system timezone
        $tz = [TimeZoneInfo]::Local.Id
        $envVars["STEALTH_GEO_TIMEZONE"] = $tz
        Write-Log "  STEALTH_GEO_TIMEZONE = $tz (system)"
    }
    
    if ($GeoLanguage) {
        $envVars["STEALTH_GEO_LANGUAGE"] = $GeoLanguage
        $envVars["STEALTH_GEO_LOCALE"] = $GeoLanguage
        Write-Log "  STEALTH_GEO_LANGUAGE = $GeoLanguage"
    }
    else {
        # Use system language
        $lang = [System.Globalization.CultureInfo]::CurrentCulture.Name
        $envVars["STEALTH_GEO_LANGUAGE"] = $lang
        $envVars["STEALTH_GEO_LOCALE"] = $lang
        Write-Log "  STEALTH_GEO_LANGUAGE = $lang (system)"
    }
    
    # ── Fingerprint Seeds (Patch 004/005) ──
    
    # Generate unique session seeds
    $sessionSeed = Get-Random -Minimum 1000000 -Maximum 9999999
    $envVars["STEALTH_SESSION_SEED"] = $sessionSeed
    
    # Canvas seed (unique per session)
    $canvasSeed = [Math]::Abs(($sessionSeed.ToString() + "-canvas").GetHashCode())
    $envVars["STEALTH_CANVAS_SEED"] = $canvasSeed
    Write-Log "  STEALTH_CANVAS_SEED = $canvasSeed (session-unique)"
    
    # WebGL seed
    $webglSeed = [Math]::Abs(($sessionSeed.ToString() + "-webgl").GetHashCode())
    $envVars["STEALTH_WEBGL_SEED"] = $webglSeed
    
    # Audio seed
    $audioSeed = [Math]::Abs(($sessionSeed.ToString() + "-audio").GetHashCode())
    $envVars["STEALTH_AUDIO_SEED"] = $audioSeed
    
    # ── Font Filter (Patch 006) ──
    
    $envVars["STEALTH_FONT_OS"] = "WINDOWS_11"
    Write-Log "  STEALTH_FONT_OS = WINDOWS_11"
    
    # Regional fonts based on GeoIP
    $fontRegionMap = @{
        "JP" = "JAPAN"
        "KR" = "KOREA"
        "CN" = "CHINA"
        "TW" = "CHINA"
        "HK" = "CHINA"
    }
    
    if ($GeoCountry -and $fontRegionMap.ContainsKey($GeoCountry)) {
        $envVars["STEALTH_FONT_REGION"] = $fontRegionMap[$GeoCountry]
    }
    else {
        $envVars["STEALTH_FONT_REGION"] = "GENERIC"
    }
    
    # ── WebRTC (Patch 010) ──
    
    $envVars["STEALTH_FILTER_WEBRTC"] = "true"
    Write-Log "  STEALTH_FILTER_WEBRTC = true"
    
    # ── Screen Resolution (if overridden) ──
    
    if ($ScreenWidth) {
        $envVars["STEALTH_SCREEN_WIDTH"] = $ScreenWidth
    }
    if ($ScreenHeight) {
        $envVars["STEALTH_SCREEN_HEIGHT"] = $ScreenHeight
    }
    
    # ── Battery (Patch 010) ──
    
    $envVars["STEALTH_SPOOF_BATTERY"] = "true"
    
    # ── Proxy IP (for WebRTC filtering) ──
    
    # If we have a proxy, try to get its exit IP
    if ($ProxyUrl) {
        # Parse proxy URL to extract host
        try {
            $uri = [Uri]$ProxyUrl
            $proxyHost = $uri.Host
            $envVars["STEALTH_PROXY_HOST"] = $proxyHost
        }
        catch {
            Write-Warning2 "  Could not parse proxy URL"
        }
    }
    
    return $envVars
}

# ═══════════════════════════════════════════════════════════
# Build Chrome Arguments
# ═══════════════════════════════════════════════════════════

function Build-ChromeArguments {
    <#
    .SYNOPSIS
    Builds the command line arguments for Chrome launch.
    #>
    
    $args = [System.Collections.Generic.List[string]]::new()
    
    # ── Essential arguments ──
    
    $essentialArgs = @(
        "--no-first-run"
        "--no-default-browser-check"
        "--disable-background-timer-throttling"
        "--disable-backgrounding-occluded-windows"
        "--disable-renderer-backgrounding"
        "--disable-background-networking"
        "--disable-client-side-phishing-detection"
        "--disable-default-apps"
        "--disable-features=site-per-process,Translate,MediaRouter,msEdgeOOBE"
        "--disable-hang-monitor"
        "--disable-prompt-on-repost"
        "--disable-sync"
        "--metrics-recording-only"
        "--no-pings"
        "--password-store=basic"
        "--use-mock-keychain"
    )
    
    foreach ($arg in $essentialArgs) {
        $args.Add($arg)
    }
    
    # ── Sandbox ──
    
    if ($NoSandbox) {
        $args.Add("--no-sandbox")
        Write-Log "  Sandbox: DISABLED (for CI/Docker)"
    }
    
    # ── Headless ──
    
    if ($Headless) {
        # Use new headless mode (less detectable than old headless)
        $args.Add("--headless=new")
        Write-Warning2 "  Headless mode enabled (more detectable!)"
    }
    else {
        # Windowed mode
        $args.Add("--start-maximized")
    }
    
    # ── Screen size ──
    
    if ($ScreenWidth -and $ScreenHeight) {
        $args.Add("--window-size=$ScreenWidth,$ScreenHeight")
        Write-Log "  Window size: ${ScreenWidth}x${ScreenHeight}"
    }
    else {
        # Use system screen resolution
        Add-Type -AssemblyName System.Windows.Forms
        $screen = [System.Windows.Forms.Screen]::PrimaryScreen
        $w = $screen.Bounds.Width
        $h = $screen.Bounds.Height
        # Subtract taskbar
        $h = $h - 40
        $args.Add("--window-size=$w,$h")
        Write-Log "  Window size: ${w}x${h} (system)"
    }
    
    # ── Proxy ──
    
    if ($ProxyUrl) {
        $args.Add("--proxy-server=$ProxyUrl")
        Write-Log "  Proxy: $ProxyUrl"
    }
    else {
        Write-Log "  Proxy: none (direct connection)"
    }
    
    # ── User data directory ──
    
    if (-not $UserDataDir) {
        # Create unique temp directory per session
        $UserDataDir = Join-Path $env:TEMP "stealth-profile-$(Get-Random -Maximum 999999)"
    }
    $args.Add("--user-data-dir=`"$UserDataDir`"")
    Write-Log "  User data: $UserDataDir"
    
    # ── Remote debugging (for driver communication) ──
    
    $args.Add("--remote-debugging-port=$DebugPort")
    Write-Log "  Debug port: $DebugPort"
    
    # ── Extra arguments ──
    
    if ($ExtraArgs) {
        foreach ($extra in $ExtraArgs) {
            $args.Add($extra)
            Write-Log "  Extra: $extra"
        }
    }
    
    return $args
}

# ═══════════════════════════════════════════════════════════
# Launch Browser
# ═══════════════════════════════════════════════════════════

function Start-Jbium {
    <#
    .SYNOPSIS
    Main launcher function.
    #>
    
    Write-Host ""
    Write-Host "══════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "  Jbium v$Script:Version" -ForegroundColor Cyan
    Write-Host "  Platform: Windows" -ForegroundColor Cyan
    Write-Host "══════════════════════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host ""
    
    # ── Find binary ──
    Write-Log "Locating browser binary..."
    $binary = Find-BrowserBinary
    $binaryInfo = Get-Item $binary
    $sizeMB = [Math]::Round($binaryInfo.Length / 1MB, 1)
    Write-Success "  Binary found: $binary ($sizeMB MB)"
    Write-Host ""
    
    # ── Setup fonts ──
    Write-Log "Setting up fonts..."
    $fontEnv = Setup-Fonts
    Write-Success "  Font setup complete"
    
    # ── Set environment variables ──
    Write-Log "Configuring stealth environment..."
    $stealthEnv = Set-StealthEnvironment
    
    # Apply environment variables
    foreach ($key in $stealthEnv.Keys) {
        [Environment]::SetEnvironmentVariable($key, $stealthEnv[$key], "Process")
    }
    
    # Apply font environment variables
    foreach ($key in $fontEnv.Keys) {
        [Environment]::SetEnvironmentVariable($key, $fontEnv[$key], "Process")
    }
    
    Write-Success "  Environment configured"
    Write-Host ""
    
    # ── Build arguments ──
    Write-Log "Building launch arguments..."
    $chromeArgs = Build-ChromeArguments
    Write-Success "  $(($chromeArgs | Measure-Object).Count) arguments prepared"
    Write-Host ""
    
    # ── Display configuration summary ──
    Write-Host "─── Configuration ─────────────────────────────────────" -ForegroundColor Gray
    Write-Host "  Binary:       $binary"
    Write-Host "  Platform:     Win32 (Windows)"
    Write-Host "  CPU cores:    $($stealthEnv['STEALTH_CPU_CORES'])"
    Write-Host "  Device RAM:   $($stealthEnv['STEALTH_DEVICE_MEMORY'])GB"
    Write-Host "  Timezone:     $($stealthEnv['STEALTH_GEO_TIMEZONE'])"
    Write-Host "  Language:     $($stealthEnv['STEALTH_GEO_LANGUAGE'])"
    Write-Host "  Proxy:        $(if ($ProxyUrl) { $ProxyUrl } else { 'None (direct)' })"
    Write-Host "  Headless:     $Headless"
    Write-Host "  Debug port:   $DebugPort"
    Write-Host "  Canvas seed:  $($stealthEnv['STEALTH_CANVAS_SEED'])"
    Write-Host "────────────────────────────────────────────────────────" -ForegroundColor Gray
    Write-Host ""
    
    # ── If NoLaunch, just return config ──
    if ($NoLaunch) {
        Write-Log "NoLaunch specified — returning configuration only"
        return @{
            Binary = $binary
            Args = $chromeArgs
            Env = $stealthEnv
            DebugPort = $DebugPort
            UserDataDir = $UserDataDir
        }
    }
    
    # ── Launch ──
    Write-Log "Launching Jbium..."
    
    try {
        $process = Start-Process `
            -FilePath $binary `
            -ArgumentList $chromeArgs `
            -PassThru `
            -WorkingDirectory (Split-Path $binary)
        
        Write-Success "  Browser launched! (PID: $($process.Id))"
        Write-Host ""
        
        # Wait for browser to be ready
        Write-Log "Waiting for browser to initialize..."
        $ready = $false
        
        for ($i = 0; $i -lt 30; $i++) {
            Start-Sleep -Milliseconds 500
            
            # Check if process is still running
            if ($process.HasExited) {
                Write-Error2 "  Browser exited unexpectedly (Code: $($process.ExitCode))"
                throw "Browser failed to start"
            }
            
            # Check if debug port is responding
            try {
                $response = Invoke-WebRequest `
                    -Uri "http://127.0.0.1:$DebugPort/json/version" `
                    -UseBasicParsing `
                    -TimeoutSec 2 `
                    -ErrorAction SilentlyContinue
                
                if ($response.StatusCode -eq 200) {
                    $ready = $true
                    break
                }
            }
            catch {
                # Port not ready yet
            }
        }
        
        if ($ready) {
            $versionInfo = ($response.Content | ConvertFrom-Json).Browser
            Write-Success "  Browser ready!"
            Write-Log "  Version: $versionInfo"
            Write-Log "  Debug: http://127.0.0.1:$DebugPort"
            Write-Host ""
            
            Write-Host "══════════════════════════════════════════════════════════" -ForegroundColor Green
            Write-Host "  ✅ Jbium Active" -ForegroundColor Green
            Write-Host "══════════════════════════════════════════════════════════" -ForegroundColor Green
            Write-Host ""
            Write-Host "  Browser is running with stealth patches active."
            Write-Host "  Press Ctrl+C to stop, or close the browser window."
            Write-Host ""
            
            # Wait for browser to close
            try {
                Wait-Process -Id $process.Id -ErrorAction SilentlyContinue
                Write-Log "Browser closed"
            }
            catch {
                # Process already exited
            }
        }
        else {
            Write-Warning2 "  Browser did not respond on debug port (may still be starting)"
        }
        
    }
    catch {
        Write-Error2 "Failed to launch browser: $_"
        throw
    }
    
    # ── Cleanup ──
    Write-Log "Cleaning up..."
    
    # Remove environment variables
    foreach ($key in $stealthEnv.Keys) {
        [Environment]::SetEnvironmentVariable($key, $null, "Process")
    }
    
    # Clean up user data directory (optional)
    if ($UserDataDir -and (Test-Path $UserDataDir)) {
        # Uncomment to clean up:
        # Remove-Item $UserDataDir -Recurse -Force -ErrorAction SilentlyContinue
        Write-Log "  User data preserved: $UserDataDir"
    }
    
    Write-Success "Done"
}

# ═══════════════════════════════════════════════════════════
# Self-Test / Diagnostics
# ═══════════════════════════════════════════════════════════

function Invoke-SelfTest {
    <#
    .SYNOPSIS
    Run diagnostic checks to verify environment.
    #>
    
    Write-Host ""
    Write-Host "══════════════════════════════════════════════════════════" -ForegroundColor Magenta
    Write-Host "  Jbium — Self Test" -ForegroundColor Magenta
    Write-Host "══════════════════════════════════════════════════════════" -ForegroundColor Magenta
    Write-Host ""
    
    $checks = @()
    
    # Check 1: PowerShell version
    $psVersion = $PSVersionTable.PSVersion
    $checks += @{
        Name = "PowerShell Version"
        Expected = "5.1+"
        Actual = $psVersion.ToString()
        Pass = ($psVersion.Major -ge 5 -and $psVersion.Minor -ge 1) -or $psVersion.Major -gt 5
    }
    
    # Check 2: .NET Framework / .NET Core
    $dotnetVersion = [System.Environment]::Version.ToString()
    $checks += @{
        Name = ".NET Runtime"
        Expected = "4.x+"
        Actual = $dotnetVersion
        Pass = $true  # Always present in Windows
    }
    
    # Check 3: Browser binary
    try {
        $binary = Find-BrowserBinary
        $checks += @{
            Name = "Browser Binary"
            Expected = "jbium.exe found"
            Actual = $binary
            Pass = $true
        }
        
        # Check binary size
        $info = Get-Item $binary
        $sizeMB = [Math]::Round($info.Length / 1MB, 0)
        $checks += @{
            Name = "Binary Size"
            Expected = "> 30 MB"
            Actual = "$sizeMB MB"
            Pass = ($sizeMB -gt 30)
        }
    }
    catch {
        $checks += @{
            Name = "Browser Binary"
            Expected = "jbium.exe found"
            Actual = "NOT FOUND"
            Pass = $false
        }
    }
    
    # Check 4: Check if binary is our stealth build
    # (Look for a marker in the binary)
    try {
        $content = [System.IO.File]::ReadAllText($binary, [System.Text.Encoding]::ASCII)
        $isStealth = $content.Contains("STEALTH") -or $content.Contains("stealth_font_filter")
        $checks += @{
            Name = "Stealth Build Detection"
            Expected = "Stealth patches present"
            Actual = if ($isStealth) { "Detected" } else { "Not detected (may be vanilla)" }
            Pass = $true  # Warning only, not blocking
        }
    }
    catch {
        $checks += @{
            Name = "Stealth Build Detection"
            Expected = "Stealth patches present"
            Actual = "Could not check"
            Pass = $false
        }
    }
    
    # Check 5: Available disk space
    $drive = Get-PSDrive -Name $env:TEMP.Substring(0,1)
    $freeGB = [Math]::Round($drive.Free / 1GB, 1)
    $checks += @{
        Name = "Disk Space (Temp)"
        Expected = "> 1 GB free"
        Actual = "$freeGB GB free"
        Pass = ($freeGB -gt 1)
    }
    
    # Check 6: Screen resolution
    Add-Type -AssemblyName System.Windows.Forms
    $screen = [System.Windows.Forms.Screen]::PrimaryScreen
    $checks += @{
        Name = "Screen Resolution"
        Expected = "> 1024x768"
        Actual = "$($screen.Bounds.Width)x$($screen.Bounds.Height)"
        Pass = ($screen.Bounds.Width -ge 1024 -and $screen.Bounds.Height -ge 768)
    }
    
    # Check 7: System timezone
    $tz = [TimeZoneInfo]::Local.Id
    $checks += @{
        Name = "System Timezone"
        Expected = "Valid timezone"
        Actual = $tz
        Pass = ($tz -match '/')
    }
    
    # Check 8: Internet connectivity
    try {
        $null = Invoke-WebRequest -Uri "https://ipv4.webshare.io/" -UseBasicParsing -TimeoutSec 5
        $netStatus = "Connected"
        $netPass = $true
    }
    catch {
        $netStatus = "Limited/No connection"
        $netPass = $false
    }
    $checks += @{
        Name = "Internet Connection"
        Expected = "Connected"
        Actual = $netStatus
        Pass = $netPass
    }
    
    # Check 9: Admin rights (for sandbox)
    $isAdmin = Test-Admin
    $checks += @{
        Name = "Admin Rights"
        Expected = "Optional (for some features)"
        Actual = if ($isAdmin) { "Yes" } else { "No (normal user)" }
        Pass = $true  # Not required
    }
    
    # Display results
    $passCount = ($checks | Where-Object { $_.Pass }).Count
    $totalCount = $checks.Count
    
    foreach ($check in $checks) {
        $icon = if ($check.Pass) { "✅" } else { "❌" }
        $color = if ($check.Pass) { "Green" } else { "Red" }
        Write-Host "  $icon $($check.Name): " -NoNewline -ForegroundColor $color
        Write-Host "$($check.Actual)" -ForegroundColor Gray
        Write-Host "     Expected: $($check.Expected)" -ForegroundColor DarkGray
    }
    
    Write-Host ""
    Write-Host "  Results: $passCount / $totalCount passed" -ForegroundColor $(if ($passCount -eq $totalCount) { "Green" } else { "Yellow" })
    Write-Host ""
    
    return ($passCount -eq $totalCount)
}

# ═══════════════════════════════════════════════════════════
# Main Execution
# ═══════════════════════════════════════════════════════════

# Check if this script is being dot-sourced (imported) or run directly
if ($MyInvocation.InvocationName -ne ".") {
    # Script is being run directly
    
    # Handle special modes
    if ($args -contains "--test" -or $args -contains "--selftest") {
        $result = Invoke-SelfTest
        exit $(if ($result) { 0 } else { 1 })
    }
    
    if ($args -contains "--help" -or $args -contains "-h") {
        Get-Help $MyInvocation.MyCommand.Path -Full
        exit 0
    }
    
    if ($args -contains "--version" -or $args -contains "-v") {
        Write-Host "Jbium Launcher v$Script:Version"
        exit 0
    }
    
    if ($args -contains "--find") {
        # Just find and report the binary location
        try {
            $binary = Find-BrowserBinary
            Write-Host "Browser binary: $binary" -ForegroundColor Green
            exit 0
        }
        catch {
            Write-Host "Browser binary: NOT FOUND" -ForegroundColor Red
            exit 1
        }
    }
    
    if ($args -contains "--config") {
        # Just show configuration, don't launch
        $NoLaunch = $true
    }
    
    # Normal launch
    try {
        Start-Jbium
    }
    catch {
        Write-Host ""
        Write-Error2 "FATAL: $_"
        Write-Host ""
        exit 1
    }
}
else {
    # Script is being dot-sourced — export functions
    Write-Host "Jbium launcher loaded. Functions available:" -ForegroundColor Cyan
    Write-Host "  Start-Jbium"
    Write-Host "  Find-BrowserBinary"
    Write-Host "  Invoke-SelfTest"
    Write-Host ""
    Write-Host "Use: Start-Jbium -ProxyUrl 'http://...'" -ForegroundColor Gray
}
