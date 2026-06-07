param(
    [string] $BindAddress = "0.0.0.0",
    [int] $Port = 1234,
    [switch] $SmokeTest
)

$ErrorActionPreference = "Stop"

# --- Crash auto-logger -------------------------------------------------------
# Captures fatal/unhandled errors (startup, background threads, WPF dispatcher)
# to a dedicated log so failures during development are easy to inspect.
$script:RepoRootEarly = Split-Path -Parent $PSScriptRoot
$script:CrashLog = Join-Path $script:RepoRootEarly "snifferops-crash.log"

function Write-CrashLog {
    param(
        [string] $Context,
        [object] $ErrorObject
    )

    try {
        $message = "Unknown error"
        $type = ""
        $stack = ""

        if ($ErrorObject -is [System.Management.Automation.ErrorRecord]) {
            $message = $ErrorObject.Exception.Message
            $type = $ErrorObject.Exception.GetType().FullName
            $stack = $ErrorObject.ScriptStackTrace
            if (-not $stack) { $stack = $ErrorObject.Exception.StackTrace }
        } elseif ($ErrorObject -is [System.Exception]) {
            $message = $ErrorObject.Message
            $type = $ErrorObject.GetType().FullName
            $stack = $ErrorObject.StackTrace
        } elseif ($ErrorObject) {
            $message = [string] $ErrorObject
        }

        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        $line = "[$timestamp] CRASH ($Context): [$type] $message"
        if ($stack) { $line += "`r`n$stack" }
        Add-Content -LiteralPath $script:CrashLog -Value $line -ErrorAction SilentlyContinue
    } catch {
        # Never let the crash logger itself throw.
    }
}

trap {
    Write-CrashLog -Context "Fatal (script scope)" -ErrorObject $_
    break
}

[AppDomain]::CurrentDomain.add_UnhandledException({
    param($eventSender, $eventArgs)
    Write-CrashLog -Context "AppDomain unhandled" -ErrorObject $eventArgs.ExceptionObject
})
# ---------------------------------------------------------------------------

Add-Type -AssemblyName PresentationFramework
Add-Type -AssemblyName PresentationCore
Add-Type -AssemblyName WindowsBase
Add-Type -Language CSharp -TypeDefinition @"
using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;

public sealed class PcmWaveStreamer : IDisposable
{
    private const int CALLBACK_FUNCTION = 0x00030000;
    private const int WAVE_MAPPER = -1;
    private const int WOM_DONE = 0x3BD;

    [StructLayout(LayoutKind.Sequential)]
    private struct WaveFormatEx
    {
        public ushort wFormatTag;
        public ushort nChannels;
        public uint nSamplesPerSec;
        public uint nAvgBytesPerSec;
        public ushort nBlockAlign;
        public ushort wBitsPerSample;
        public ushort cbSize;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct WaveHdr
    {
        public IntPtr lpData;
        public uint dwBufferLength;
        public uint dwBytesRecorded;
        public IntPtr dwUser;
        public uint dwFlags;
        public uint dwLoops;
        public IntPtr lpNext;
        public IntPtr reserved;
    }

    private delegate void WaveOutProc(IntPtr hwo, uint uMsg, IntPtr dwInstance, IntPtr dwParam1, IntPtr dwParam2);

    [DllImport("winmm.dll")]
    private static extern int waveOutOpen(out IntPtr hWaveOut, int uDeviceID, ref WaveFormatEx lpFormat, WaveOutProc dwCallback, IntPtr dwInstance, int dwFlags);

    [DllImport("winmm.dll")]
    private static extern int waveOutPrepareHeader(IntPtr hWaveOut, ref WaveHdr lpWaveOutHdr, uint uSize);

    [DllImport("winmm.dll")]
    private static extern int waveOutWrite(IntPtr hWaveOut, ref WaveHdr lpWaveOutHdr, uint uSize);

    [DllImport("winmm.dll")]
    private static extern int waveOutUnprepareHeader(IntPtr hWaveOut, ref WaveHdr lpWaveOutHdr, uint uSize);

    [DllImport("winmm.dll")]
    private static extern int waveOutReset(IntPtr hWaveOut);

    [DllImport("winmm.dll")]
    private static extern int waveOutClose(IntPtr hWaveOut);

    private readonly AutoResetEvent bufferDone = new AutoResetEvent(false);
    private readonly object sync = new object();
    private WaveOutProc callback;
    private Process process;
    private Thread worker;
    private IntPtr waveOut = IntPtr.Zero;
    private volatile bool stopRequested;
    private string errorText = "";

    public string ErrorText { get { lock (sync) { return errorText; } } }
    public bool IsRunning { get { return worker != null && worker.IsAlive; } }

    public void Start(string exePath, string arguments, string workingDirectory, int sampleRate)
    {
        Stop();
        stopRequested = false;
        lock (sync) { errorText = ""; }

        worker = new Thread(() => Run(exePath, arguments, workingDirectory, sampleRate));
        worker.IsBackground = true;
        worker.Start();
    }

    private void Run(string exePath, string arguments, string workingDirectory, int sampleRate)
    {
        try
        {
            callback = (hwo, msg, inst, p1, p2) =>
            {
                if (msg == WOM_DONE) bufferDone.Set();
            };

            var format = new WaveFormatEx
            {
                wFormatTag = 1,
                nChannels = 1,
                nSamplesPerSec = (uint)sampleRate,
                wBitsPerSample = 16,
                nBlockAlign = 2,
                nAvgBytesPerSec = (uint)(sampleRate * 2),
                cbSize = 0
            };

            int openResult = waveOutOpen(out waveOut, WAVE_MAPPER, ref format, callback, IntPtr.Zero, CALLBACK_FUNCTION);
            if (openResult != 0) throw new InvalidOperationException("waveOutOpen failed: " + openResult);

            var psi = new ProcessStartInfo
            {
                FileName = exePath,
                Arguments = arguments,
                WorkingDirectory = workingDirectory,
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true
            };

            process = Process.Start(psi);
            var errorThread = new Thread(() =>
            {
                try
                {
                    string err = process.StandardError.ReadToEnd();
                    if (!String.IsNullOrWhiteSpace(err)) lock (sync) { errorText = err.Trim(); }
                }
                catch { }
            });
            errorThread.IsBackground = true;
            errorThread.Start();

            Stream output = process.StandardOutput.BaseStream;
            byte[] readBuffer = new byte[8192];

            while (!stopRequested)
            {
                int read = output.Read(readBuffer, 0, readBuffer.Length);
                if (read <= 0) break;

                IntPtr data = Marshal.AllocHGlobal(read);
                Marshal.Copy(readBuffer, 0, data, read);
                var header = new WaveHdr { lpData = data, dwBufferLength = (uint)read };
                uint headerSize = (uint)Marshal.SizeOf(typeof(WaveHdr));

                waveOutPrepareHeader(waveOut, ref header, headerSize);
                bufferDone.Reset();
                waveOutWrite(waveOut, ref header, headerSize);
                bufferDone.WaitOne(1000);
                waveOutUnprepareHeader(waveOut, ref header, headerSize);
                Marshal.FreeHGlobal(data);
            }
        }
        catch (Exception ex)
        {
            lock (sync) { errorText = ex.Message; }
        }
        finally
        {
            try { if (process != null && !process.HasExited) process.Kill(); } catch { }
            try { if (waveOut != IntPtr.Zero) waveOutReset(waveOut); } catch { }
            try { if (waveOut != IntPtr.Zero) waveOutClose(waveOut); } catch { }
            waveOut = IntPtr.Zero;
            process = null;
        }
    }

    public void Stop()
    {
        stopRequested = true;
        try { if (process != null && !process.HasExited) process.Kill(); } catch { }
        try { if (waveOut != IntPtr.Zero) waveOutReset(waveOut); } catch { }
        try { if (worker != null && worker.IsAlive) worker.Join(1200); } catch { }
        worker = null;
    }

    public void Dispose()
    {
        Stop();
        bufferDone.Dispose();
    }
}

public sealed class RtlTcpWaveStreamer : IDisposable
{
    private const int CALLBACK_FUNCTION = 0x00030000;
    private const int WAVE_MAPPER = -1;
    private const int WOM_DONE = 0x3BD;

    [StructLayout(LayoutKind.Sequential)]
    private struct WaveFormatEx
    {
        public ushort wFormatTag;
        public ushort nChannels;
        public uint nSamplesPerSec;
        public uint nAvgBytesPerSec;
        public ushort nBlockAlign;
        public ushort wBitsPerSample;
        public ushort cbSize;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct WaveHdr
    {
        public IntPtr lpData;
        public uint dwBufferLength;
        public uint dwBytesRecorded;
        public IntPtr dwUser;
        public uint dwFlags;
        public uint dwLoops;
        public IntPtr lpNext;
        public IntPtr reserved;
    }

    private delegate void WaveOutProc(IntPtr hwo, uint uMsg, IntPtr dwInstance, IntPtr dwParam1, IntPtr dwParam2);

    [DllImport("winmm.dll")]
    private static extern int waveOutOpen(out IntPtr hWaveOut, int uDeviceID, ref WaveFormatEx lpFormat, WaveOutProc dwCallback, IntPtr dwInstance, int dwFlags);

    [DllImport("winmm.dll")]
    private static extern int waveOutPrepareHeader(IntPtr hWaveOut, ref WaveHdr lpWaveOutHdr, uint uSize);

    [DllImport("winmm.dll")]
    private static extern int waveOutWrite(IntPtr hWaveOut, ref WaveHdr lpWaveOutHdr, uint uSize);

    [DllImport("winmm.dll")]
    private static extern int waveOutUnprepareHeader(IntPtr hWaveOut, ref WaveHdr lpWaveOutHdr, uint uSize);

    [DllImport("winmm.dll")]
    private static extern int waveOutReset(IntPtr hWaveOut);

    [DllImport("winmm.dll")]
    private static extern int waveOutClose(IntPtr hWaveOut);

    private readonly AutoResetEvent bufferDone = new AutoResetEvent(false);
    private readonly object sync = new object();
    private WaveOutProc callback;
    private Thread worker;
    private IntPtr waveOut = IntPtr.Zero;
    private volatile bool stopRequested;
    private string errorText = "";

    public string ErrorText { get { lock (sync) { return errorText; } } }
    public bool IsRunning { get { return worker != null && worker.IsAlive; } }

    public void Start(string host, int port, long frequency, string mode)
    {
        Stop();
        stopRequested = false;
        lock (sync) { errorText = ""; }
        worker = new Thread(() => Run(host, port, frequency, mode ?? "fm"));
        worker.IsBackground = true;
        worker.Start();
    }

    private static void WriteCommand(Stream stream, byte command, uint parameter)
    {
        byte[] bytes = new byte[] {
            command,
            (byte)((parameter >> 24) & 0xff),
            (byte)((parameter >> 16) & 0xff),
            (byte)((parameter >> 8) & 0xff),
            (byte)(parameter & 0xff)
        };
        stream.Write(bytes, 0, bytes.Length);
        stream.Flush();
    }

    private void Run(string host, int port, long frequency, string mode)
    {
        System.Net.Sockets.TcpClient client = null;
        try
        {
            int audioRate = 48000;
            int iqRate = 240000;
            int decimation = iqRate / audioRate;

            callback = (hwo, msg, inst, p1, p2) =>
            {
                if (msg == WOM_DONE) bufferDone.Set();
            };

            var format = new WaveFormatEx
            {
                wFormatTag = 1,
                nChannels = 1,
                nSamplesPerSec = (uint)audioRate,
                wBitsPerSample = 16,
                nBlockAlign = 2,
                nAvgBytesPerSec = (uint)(audioRate * 2),
                cbSize = 0
            };

            int openResult = waveOutOpen(out waveOut, WAVE_MAPPER, ref format, callback, IntPtr.Zero, CALLBACK_FUNCTION);
            if (openResult != 0) throw new InvalidOperationException("waveOutOpen failed: " + openResult);

            client = new System.Net.Sockets.TcpClient();
            var connect = client.BeginConnect(host, port, null, null);
            if (!connect.AsyncWaitHandle.WaitOne(2000, false)) throw new IOException("Could not connect to rtl_tcp at " + host + ":" + port);
            client.EndConnect(connect);
            client.ReceiveTimeout = 2000;
            client.SendTimeout = 2000;

            Stream stream = client.GetStream();
            WriteCommand(stream, 0x02, (uint)iqRate);
            WriteCommand(stream, 0x03, 0);
            WriteCommand(stream, 0x04, 0);
            WriteCommand(stream, 0x01, (uint)frequency);

            byte[] iq = new byte[65536];
            double previousPhase = 0.0;
            double averageMagnitude = 70.0;
            bool phaseInitialized = false;
            double audioAccumulator = 0.0;
            int decimationCounter = 0;

            while (!stopRequested)
            {
                int read = stream.Read(iq, 0, iq.Length);
                if (read <= 0) break;

                int pairs = read / 2;
                short[] pcm = new short[Math.Max(1, (pairs / decimation) + 1)];
                int pcmIndex = 0;

                for (int i = 0; i < pairs; i++)
                {
                    double iSample = iq[i * 2] - 127.5;
                    double qSample = iq[i * 2 + 1] - 127.5;
                    double audio;

                    if (mode.Equals("am", StringComparison.OrdinalIgnoreCase))
                    {
                        double mag = Math.Sqrt(iSample * iSample + qSample * qSample);
                        averageMagnitude = (averageMagnitude * 0.995) + (mag * 0.005);
                        audio = (mag - averageMagnitude) * 600.0;
                    }
                    else
                    {
                        double phase = Math.Atan2(qSample, iSample);
                        double delta = phaseInitialized ? phase - previousPhase : 0.0;
                        phaseInitialized = true;
                        previousPhase = phase;
                        while (delta > Math.PI) delta -= 2.0 * Math.PI;
                        while (delta < -Math.PI) delta += 2.0 * Math.PI;
                        audio = delta * 7000.0;
                    }

                    audioAccumulator += audio;
                    decimationCounter++;
                    if (decimationCounter >= decimation)
                    {
                        double averaged = audioAccumulator / decimationCounter;
                        audioAccumulator = 0.0;
                        decimationCounter = 0;

                        if (averaged > short.MaxValue) averaged = short.MaxValue;
                        if (averaged < short.MinValue) averaged = short.MinValue;
                        if (pcmIndex < pcm.Length) pcm[pcmIndex++] = (short)averaged;
                    }
                }

                if (pcmIndex > 0) WritePcm(pcm, pcmIndex);
            }
        }
        catch (Exception ex)
        {
            lock (sync) { errorText = ex.Message; }
        }
        finally
        {
            try { if (client != null) client.Close(); } catch { }
            try { if (waveOut != IntPtr.Zero) waveOutReset(waveOut); } catch { }
            try { if (waveOut != IntPtr.Zero) waveOutClose(waveOut); } catch { }
            waveOut = IntPtr.Zero;
        }
    }

    private void WritePcm(short[] samples, int count)
    {
        int byteCount = count * 2;
        byte[] bytes = new byte[byteCount];
        Buffer.BlockCopy(samples, 0, bytes, 0, byteCount);

        IntPtr data = Marshal.AllocHGlobal(byteCount);
        Marshal.Copy(bytes, 0, data, byteCount);
        var header = new WaveHdr { lpData = data, dwBufferLength = (uint)byteCount };
        uint headerSize = (uint)Marshal.SizeOf(typeof(WaveHdr));

        waveOutPrepareHeader(waveOut, ref header, headerSize);
        bufferDone.Reset();
        waveOutWrite(waveOut, ref header, headerSize);
        bufferDone.WaitOne(1000);
        waveOutUnprepareHeader(waveOut, ref header, headerSize);
        Marshal.FreeHGlobal(data);
    }

    public void Stop()
    {
        stopRequested = true;
        try { if (waveOut != IntPtr.Zero) waveOutReset(waveOut); } catch { }
        try { if (worker != null && worker.IsAlive) worker.Join(1200); } catch { }
        worker = null;
    }

    public void Dispose()
    {
        Stop();
        bufferDone.Dispose();
    }
}
"@

Add-Type -Language CSharp -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public static class TaskbarIdentity
{
    [DllImport("shell32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern int SetCurrentProcessExplicitAppUserModelID(string appID);

    public static void Set(string appID)
    {
        SetCurrentProcessExplicitAppUserModelID(appID);
    }
}
"@
[TaskbarIdentity]::Set("SnifferOps.Windows")

$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
# Tool bitness varies by install; prefer x64 but fall back to x86 (the only one
# actually shipped in this repo) or the rtl-sdr-blog root.
$ToolRoot = @(
    (Join-Path $RepoRoot "tools\rtl-sdr-blog\x64"),
    (Join-Path $RepoRoot "tools\rtl-sdr-blog\x86"),
    (Join-Path $RepoRoot "tools\rtl-sdr-blog")
) | Where-Object { Test-Path (Join-Path $_ "rtl_tcp.exe") } | Select-Object -First 1
if (-not $ToolRoot) { $ToolRoot = Join-Path $RepoRoot "tools\rtl-sdr-blog\x64" }
$RtlTcpPath = Join-Path $ToolRoot "rtl_tcp.exe"
$RtlTestPath = Join-Path $ToolRoot "rtl_test.exe"
$RtlFmPath = Join-Path $ToolRoot "rtl_fm.exe"
$RtlAdsbPath = Join-Path $ToolRoot "rtl_adsb.exe"
$RtlPowerPath = Join-Path $ToolRoot "rtl_power.exe"
$StartRtlTcpScript = Join-Path $RepoRoot "scripts\start-rtl-tcp.ps1"
$AppIconPath = Join-Path $PSScriptRoot "assets\snifferops.ico"
$AppIconImagePath = Join-Path $PSScriptRoot "assets\snifferops-tile.png"
$AppFontPath = Join-Path $PSScriptRoot "assets\fonts\spyagency3ital.ttf"
$AppCondensedFontPath = Join-Path $PSScriptRoot "assets\fonts\spyagency3cond.ttf"
$AppGradientFontPath = Join-Path $PSScriptRoot "assets\fonts\spyagency3gradital.ttf"
$OutLog = Join-Path $RepoRoot "rtl_tcp.out.log"
$ErrLog = Join-Path $RepoRoot "rtl_tcp.err.log"
$AppLog = Join-Path $RepoRoot "snifferops-windows.log"
$AwarenessLog = Join-Path $RepoRoot "data\signal-awareness.json"
$AwarenessSyncPort = 8765
$script:RtlTcpProcess = $null
$script:ScanTimer = $null
$script:SweepTimer = $null
$script:SweepAngle = 0.0
$script:ScanActive = $false
$script:StartTime = $null
$script:BrushConverter = New-Object System.Windows.Media.BrushConverter
$script:AppFontFamily = $null
if (Test-Path -LiteralPath $AppFontPath) {
    $fontUri = [Uri]::new($AppFontPath).AbsoluteUri
    $script:AppFontFamily = New-Object System.Windows.Media.FontFamily("${fontUri}#Spy Agency Italic")
}
$script:CondensedFontFamily = $null
if (Test-Path -LiteralPath $AppCondensedFontPath) {
    $fontUri = [Uri]::new($AppCondensedFontPath).AbsoluteUri
    $script:CondensedFontFamily = New-Object System.Windows.Media.FontFamily("${fontUri}#Spy Agency Condensed")
}
$script:GradientFontFamily = $null
if (Test-Path -LiteralPath $AppGradientFontPath) {
    $fontUri = [Uri]::new($AppGradientFontPath).AbsoluteUri
    $script:GradientFontFamily = New-Object System.Windows.Media.FontFamily("${fontUri}#Spy Agency Gradient Italic")
}
$script:SdrSignals = @()
$script:SdrPowerScanCompleted = $false
$script:AudioStreamer = $null
$script:RestartRtlTcpAfterListen = $false
$script:TunerStreamer = $null            # PcmWaveStreamer driving rtl_fm for the tuner
$script:TunerRestartRtlTcp = $false      # whether to restart rtl_tcp when the tuner stops

# --- Signal lens registration ----------------------------------------------
# All lenses are registered here, explicitly, in one place (no auto-discovery).
# Each lens lives in its own file under lenses/ and is independently testable.
$LensDir = Join-Path $PSScriptRoot "lenses"
. (Join-Path $LensDir "_LensContract.ps1")
. (Join-Path $LensDir "BroadcastFMLens.ps1")
. (Join-Path $LensDir "AviationVoiceLens.ps1")
. (Join-Path $LensDir "NOAAWeatherLens.ps1")
. (Join-Path $LensDir "AnalogVoiceLens.ps1")
. (Join-Path $LensDir "ADSBLens.ps1")
. (Join-Path $LensDir "P25Phase1Lens.ps1")
. (Join-Path $LensDir "POCSAGLens.ps1")
. (Join-Path $LensDir "ACARSLens.ps1")

# ADS-B decoder + pluggable map backend (decoder is pure/testable; map renders).
$AdsbDir = Join-Path $PSScriptRoot "adsb"
. (Join-Path $AdsbDir "AdsbDecoder.ps1")
. (Join-Path $AdsbDir "AdsbMap.ps1")
# Override this scriptblock (param $JsonPath) to plug in an offline map program.
$script:AdsbMapBackend = $null
$script:AdsbCaptureSeconds = 90
$script:AdsbCaptureChunkSeconds = 15

# Shared WiFi/Bluetooth/SDR classification and explanation rules.
. (Join-Path $PSScriptRoot "SignalClassifier.ps1")

# Durable signal awareness log + optional LAN sync with Android nodes.
. (Join-Path $PSScriptRoot "AwarenessLog.ps1")
Initialize-AwarenessLog -Path $AwarenessLog

# Real spectrum scan (rtl_power): pure CSV parsing + peak detection live here.
. (Join-Path $PSScriptRoot "spectrum\PowerScan.ps1")
$script:PowerScanRange = "88M:1000M:50k"   # rtl_power -f range
$script:PowerScanThresholdDb = 10.0         # dB above local noise floor to count as a hit

# Fixed tuner gain (dB). "auto" lets the tuner AGC hunt, which causes a surging /
# pumping sound on broadcast FM. A fixed value keeps the level steady. Bump up if
# weak stations are too quiet, down if strong locals distort.
$script:DefaultTunerGain = "30"

$script:Lenses = @(
    New-BroadcastFMLens
    New-AviationVoiceLens
    New-NOAAWeatherLens
    New-AnalogVoiceLens
    New-ADSBLens
    New-P25Phase1Lens
    New-POCSAGLens
    New-ACARSLens
)
foreach ($lens in $script:Lenses) { [void] (Test-SignalLens -Lens $lens) }

function Get-MatchingLenses {
    param([object] $Signal)
    return @($script:Lenses | Where-Object { $_.CanHandle($Signal) })
}

# Signal-type indicator derived from lens availability.
#   Green  : at least one implemented lens matches
#   Yellow : only stub lenses match (decoder is on the roadmap)
#   Red    : no lens matches at all
function Get-SignalLensStatus {
    param([object] $Signal)

    $green = [char]::ConvertFromUtf32(0x1F7E2)
    $yellow = [char]::ConvertFromUtf32(0x1F7E1)
    $red = [char]::ConvertFromUtf32(0x1F534)

    $matches = Get-MatchingLenses -Signal $Signal
    if ($matches.Count -eq 0) {
        return [pscustomobject]@{ Dot = "Red"; Glyph = $red; Primary = $null; Matches = @() }
    }
    $implemented = @($matches | Where-Object { $_.Implemented })
    if ($implemented.Count -gt 0) {
        return [pscustomobject]@{ Dot = "Green"; Glyph = $green; Primary = $implemented[0]; Matches = $matches }
    }
    return [pscustomobject]@{ Dot = "Yellow"; Glyph = $yellow; Primary = $matches[0]; Matches = $matches }
}

# Builds the "Decoder" cell text shown in the signal grids.
function Get-SignalDecoderText {
    param([object] $Signal)

    $status = Get-SignalLensStatus -Signal $Signal
    if (-not $status.Primary) {
        return ("{0} No decoder available" -f $status.Glyph)
    }
    $suffix = if ($status.Primary.Implemented) { "" } else { " (not built)" }
    return ("{0} {1}{2}" -f $status.Glyph, $status.Primary.GetDisplayName(), $suffix)
}
# ---------------------------------------------------------------------------

function Write-AppError {
    param(
        [string] $Context,
        [object] $ErrorObject
    )

    $message = if ($ErrorObject -and $ErrorObject.Exception) {
        $ErrorObject.Exception.Message
    } elseif ($ErrorObject) {
        [string]$ErrorObject
    } else {
        "Unknown error"
    }

    $line = "[{0}] {1}: {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Context, $message
    Add-Content -LiteralPath $AppLog -Value $line -ErrorAction SilentlyContinue

    if ($LogBox) {
        Add-LogLine "$Context failed: $message"
    }
}

function Invoke-AppAction {
    param(
        [string] $Context,
        [scriptblock] $Action
    )

    try {
        & $Action
    } catch {
        Write-AppError -Context $Context -ErrorObject $_
        [System.Windows.MessageBox]::Show(
            "SnifferOps hit an error in $Context.`r`n`r`n$($_.Exception.Message)`r`n`r`nThe app stayed open and wrote details to snifferops-windows.log.",
            "SnifferOps Windows",
            [System.Windows.MessageBoxButton]::OK,
            [System.Windows.MessageBoxImage]::Warning
        ) | Out-Null
    }
}

function Set-SnifferOpsWindowIcon {
    param([System.Windows.Window] $TargetWindow)

    if ($TargetWindow -and (Test-Path -LiteralPath $AppIconPath)) {
        $TargetWindow.Icon = [System.Windows.Media.Imaging.BitmapFrame]::Create(
            [Uri]::new($AppIconPath, [UriKind]::Absolute)
        )
    }
}

function Set-SnifferOpsImageSource {
    param([System.Windows.Controls.Image] $TargetImage)

    if ($TargetImage -and (Test-Path -LiteralPath $AppIconImagePath)) {
        $TargetImage.Source = [System.Windows.Media.Imaging.BitmapImage]::new(
            [Uri]::new($AppIconImagePath, [UriKind]::Absolute)
        )
    }
}

function Apply-SnifferOpsFont {
    param([System.Windows.DependencyObject] $Root)

    if (-not $script:AppFontFamily -or -not $Root) { return }

    if ($Root -is [System.Windows.Controls.Control]) {
        $Root.FontFamily = $script:AppFontFamily
    } elseif ($Root -is [System.Windows.Controls.TextBlock]) {
        $Root.FontFamily = $script:AppFontFamily
    }

    $count = [System.Windows.Media.VisualTreeHelper]::GetChildrenCount($Root)
    for ($i = 0; $i -lt $count; $i++) {
        Apply-SnifferOpsFont -Root ([System.Windows.Media.VisualTreeHelper]::GetChild($Root, $i))
    }
}

function Apply-SnifferOpsSpecialFonts {
    param([System.Windows.DependencyObject] $Root)

    if (-not $Root) { return }

    if ($Root -is [System.Windows.FrameworkElement]) {
        if ($script:CondensedFontFamily -and $Root.Tag -eq "Condensed") {
            if ($Root -is [System.Windows.Controls.Control]) {
                $Root.FontFamily = $script:CondensedFontFamily
            } elseif ($Root -is [System.Windows.Controls.TextBlock]) {
                $Root.FontFamily = $script:CondensedFontFamily
            }
        }
        if ($script:GradientFontFamily -and $Root.Tag -eq "GradientTitle" -and $Root -is [System.Windows.Controls.TextBlock]) {
            $Root.FontFamily = $script:GradientFontFamily
        }
    }

    $count = [System.Windows.Media.VisualTreeHelper]::GetChildrenCount($Root)
    for ($i = 0; $i -lt $count; $i++) {
        Apply-SnifferOpsSpecialFonts -Root ([System.Windows.Media.VisualTreeHelper]::GetChild($Root, $i))
    }
}

$script:SdrScanFrequencies = @(
    88000000,
    108500000,
    137500000,
    154000000,
    162400000,
    433920000,
    462562500,
    851000000,
    915000000,
    978000000,
    1090000000
)

function Format-Frequency {
    param([long] $Frequency)

    if ($Frequency -ge 1000000000) {
        return "{0:N3} GHz" -f ($Frequency / 1000000000.0)
    }
    if ($Frequency -ge 1000000) {
        return "{0:N3} MHz" -f ($Frequency / 1000000.0)
    }
    if ($Frequency -ge 1000) {
        return "{0:N1} kHz" -f ($Frequency / 1000.0)
    }
    return "$Frequency Hz"
}

function Get-SdrClassification {
    param([long] $Frequency)

    $explanation = Get-SdrSignalExplanation -Frequency $Frequency

    return [pscustomobject][ordered]@{
        Label = $explanation.SpecificType
        Modulation = $explanation.Modulation
        Confidence = $explanation.Confidence
        Evidence = $explanation.Evidence
        Description = $explanation.Meaning
        NextStep = $explanation.NextStep
    }
}

function Get-SdrAudioExpectation {
    param(
        [string] $Label,
        [string] $Modulation
    )

    if ($Label -match "FM Radio") { return "Likely audible broadcast audio if a station is active at this exact frequency" }
    if ($Label -match "Aviation") { return "Likely audible AM voice only when aircraft/ground traffic is active" }
    if ($Label -match "NOAA Weather Radio|Public Safety VHF|Amateur|UHF Land Mobile|VHF Government") { return "May be audible narrowband voice if analog traffic is active" }
    if ($Label -match "ADS-B|P25|DME|TACAN|GPS|LoRa|ZigBee|Cellular|LTE|GSM|WiFi|Bluetooth|Satellite|ISM") { return "Digital/data signal; expect silence, bursts, or static instead of voice" }
    if ($Modulation -match "Unknown") { return "Unknown modulation; may be static unless this is analog traffic" }
    return "May be audible if analog traffic is active"
}

function Write-RtlTcpCommand {
    param(
        [System.IO.Stream] $Stream,
        [int] $Command,
        [int64] $Parameter
    )

    $value = [uint32]$Parameter
    $bytes = [byte[]]@(
        [byte]($Command -band 0xFF),
        [byte](($value -shr 24) -band 0xFF),
        [byte](($value -shr 16) -band 0xFF),
        [byte](($value -shr 8) -band 0xFF),
        [byte]($value -band 0xFF)
    )
    $Stream.Write($bytes, 0, $bytes.Length)
    $Stream.Flush()
}

function Get-IqPower {
    param(
        [byte[]] $Buffer,
        [int] $Length
    )

    $pairs = [Math]::Floor($Length / 2)
    if ($pairs -le 0) { return -120.0 }

    $sumSq = 0.0
    for ($i = 0; $i -lt $pairs; $i++) {
        $iSample = [double]$Buffer[$i * 2] - 127.5
        $qSample = [double]$Buffer[$i * 2 + 1] - 127.5
        $sumSq += ($iSample * $iSample) + ($qSample * $qSample)
    }

    $rms = [Math]::Sqrt($sumSq / $pairs)
    if ($rms -le 0) { return -120.0 }
    return 20.0 * [Math]::Log10($rms)
}

function Invoke-SdrFrequencySweep {
    $client = $null
    $signals = @()

    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $connect = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        if (-not $connect.AsyncWaitHandle.WaitOne(1500, $false)) {
            throw "Could not connect to rtl_tcp on 127.0.0.1:$Port"
        }
        $client.EndConnect($connect)
        $client.ReceiveTimeout = 1600
        $client.SendTimeout = 1600

        $stream = $client.GetStream()
        Write-RtlTcpCommand -Stream $stream -Command 0x02 -Parameter 1024000
        Write-RtlTcpCommand -Stream $stream -Command 0x03 -Parameter 0
        Write-RtlTcpCommand -Stream $stream -Command 0x04 -Parameter 0

        foreach ($frequency in $script:SdrScanFrequencies) {
            Write-RtlTcpCommand -Stream $stream -Command 0x01 -Parameter $frequency
            Start-Sleep -Milliseconds 120

            $buffer = New-Object byte[] 16384
            $read = $stream.Read($buffer, 0, $buffer.Length)
            if ($read -gt 0) {
                $power = Get-IqPower -Buffer $buffer -Length $read
                if ($power -gt -80.0) {
                    $class = Get-SdrClassification -Frequency $frequency
                    $expectation = Get-SdrAudioExpectation -Label $class.Label -Modulation $class.Modulation
                    $row = [pscustomobject][ordered]@{
                        Decoder = ""
                        Frequency = Format-Frequency -Frequency $frequency
                        FrequencyHz = $frequency
                        PowerDb = "{0:N1}" -f $power
                        Bandwidth = "1.024 MHz"
                        Label = $class.Label
                        Modulation = $class.Modulation
                        PossibleUse = $class.Label
                        Audio = $expectation
                        Confidence = $class.Confidence
                        Evidence = $class.Evidence
                        Description = $class.Description
                        NextStep = $class.NextStep
                        Source = "rtl_tcp"
                    }
                    $row.Decoder = Get-SignalDecoderText -Signal $row
                    $signals += $row
                }
            }
        }
    } catch {
        $signals += [pscustomobject][ordered]@{
            Decoder = ""
            Frequency = "SDR scan failed"
            FrequencyHz = ""
            PowerDb = ""
            Bandwidth = ""
            Label = "Error"
            Modulation = ""
            PossibleUse = $_.Exception.Message
            Source = "rtl_tcp"
        }
    } finally {
        if ($client) { $client.Close() }
    }

    $script:SdrSignals = $signals
    $script:SdrPowerScanCompleted = $true
    return $signals
}

# Real wideband power sweep with rtl_power: measures actual power-vs-frequency and
# detects peaks above the noise floor, so hits are genuine RF energy rather than
# fixed band guesses. Needs exclusive dongle access, so rtl_tcp is paused.
function Invoke-SdrPowerScan {
    if (-not (Test-Path $RtlPowerPath)) {
        Add-LogLine "Missing rtl_power.exe in $ToolRoot."
        return @()
    }

    $csvPath = Join-Path $RepoRoot "rtl_power.out.csv"
    $errPath = Join-Path $RepoRoot "rtl_power.err.log"

    $serverWasRunning = [bool](Get-Process rtl_tcp -ErrorAction SilentlyContinue)
    if ($serverWasRunning) {
        Add-LogLine "Pausing rtl_tcp for wideband power scan..."
        Get-Process rtl_tcp -ErrorAction SilentlyContinue | Stop-Process -Force
        Start-Sleep -Milliseconds 500
    }

    if (Test-Path $csvPath) { Remove-Item -LiteralPath $csvPath -Force }
    if (Test-Path $errPath) { Remove-Item -LiteralPath $errPath -Force }

    Add-LogLine "Running rtl_power over $($script:PowerScanRange) (single pass)..."
    $argList = "-f $($script:PowerScanRange) -i 1 -1 `"$csvPath`""
    $proc = Start-Process -FilePath $RtlPowerPath `
        -ArgumentList $argList `
        -WorkingDirectory $ToolRoot `
        -RedirectStandardError $errPath `
        -WindowStyle Hidden `
        -PassThru

    try {
        $deadline = (Get-Date).AddSeconds(90)
        while ((Get-Date) -lt $deadline -and -not $proc.HasExited) {
            Start-Sleep -Milliseconds 500
        }
    } finally {
        if (-not $proc.HasExited) { try { $proc.Kill() } catch {} }
    }
    Start-Sleep -Milliseconds 300

    $signals = @()
    try {
        if (-not (Test-Path $csvPath)) {
            $errText = if (Test-Path $errPath) { (Get-Content $errPath -Raw).Trim() } else { "rtl_power produced no output" }
            Add-LogLine "Power scan failed: $errText"
        } else {
            $lines = @(Get-Content -Path $csvPath -ErrorAction SilentlyContinue)
            $bins = ConvertFrom-RtlPowerCsv -Lines $lines
            $peaks = @(Find-SpectrumPeaks -Bins $bins -ThresholdDb $script:PowerScanThresholdDb)
            Add-LogLine "Power scan: $($bins.Count) bins scanned, $($peaks.Count) peak(s) >= $($script:PowerScanThresholdDb)dB above local floor."

            foreach ($peak in $peaks) {
                $class = Get-SdrClassification -Frequency $peak.FrequencyHz
                $expectation = Get-SdrAudioExpectation -Label $class.Label -Modulation $class.Modulation
                $row = [pscustomobject][ordered]@{
                    Decoder = ""
                    Frequency = Format-Frequency -Frequency $peak.FrequencyHz
                    FrequencyHz = $peak.FrequencyHz
                    PowerDb = "{0:N1}" -f $peak.PowerDb
                    Bandwidth = $script:PowerScanRange
                    Label = $class.Label
                    Modulation = $class.Modulation
                    PossibleUse = $class.Label
                    Audio = $expectation
                    Confidence = $class.Confidence
                    Evidence = Join-NonEmptyText -Values @($class.Evidence, ("{0:N1} dB above local floor" -f $peak.ProminenceDb))
                    Description = $class.Description
                    NextStep = $class.NextStep
                    Source = "rtl_power"
                }
                $row.Decoder = Get-SignalDecoderText -Signal $row
                $signals += $row
            }
        }
    } catch {
        Add-LogLine "Power scan parse error: $($_.Exception.Message)"
    }

    if ($serverWasRunning) { Start-RtlTcpServer }

    $script:SdrSignals = $signals
    return $signals
}

function Get-LanIpAddress {
    $ip = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object {
            $_.IPAddress -notlike "127.*" -and
            $_.IPAddress -notlike "169.254.*" -and
            $_.PrefixOrigin -ne "WellKnown"
        } |
        Sort-Object -Property InterfaceMetric, InterfaceIndex |
        Select-Object -First 1 -ExpandProperty IPAddress

    if ([string]::IsNullOrWhiteSpace($ip)) {
        return "127.0.0.1"
    }

    return $ip
}

function Get-WifiCount {
    try {
        $output = netsh wlan show networks mode=bssid 2>$null
        return @($output | Where-Object { $_ -match '^\s*SSID\s+\d+\s+:' }).Count
    } catch {
        return 0
    }
}

function Get-BluetoothCount {
    try {
        return @(Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue |
            Where-Object { $_.Status -eq "OK" }).Count
    } catch {
        return 0
    }
}

function Get-WifiDetails {
    $items = @()
    try {
        $output = netsh wlan show networks mode=bssid 2>$null
        $current = $null
        foreach ($line in $output) {
            if ($line -match '^\s*SSID\s+\d+\s+:\s*(.*)$') {
                if ($current) {
                    $wifiRow = [pscustomobject]$current
                    $info = Get-WifiSignalExplanation -Wifi $wifiRow
                    $wifiRow | Add-Member -NotePropertyName SpecificType -NotePropertyValue $info.SpecificType
                    $wifiRow | Add-Member -NotePropertyName Confidence -NotePropertyValue $info.Confidence
                    $wifiRow | Add-Member -NotePropertyName Evidence -NotePropertyValue $info.Evidence
                    $wifiRow | Add-Member -NotePropertyName Meaning -NotePropertyValue $info.Meaning
                    $wifiRow | Add-Member -NotePropertyName NextStep -NotePropertyValue $info.NextStep
                    $items += $wifiRow
                }
                $ssid = $Matches[1].Trim()
                if ([string]::IsNullOrWhiteSpace($ssid)) { $ssid = "<hidden>" }
                $current = [ordered]@{
                    Name = $ssid
                    Address = ""
                    Strength = ""
                    Channel = ""
                    Security = ""
                    Type = "Wi-Fi"
                    Notes = ""
                }
                continue
            }

            if (-not $current) { continue }

            if ($line -match '^\s*Authentication\s+:\s*(.*)$') {
                $current.Security = $Matches[1].Trim()
            } elseif ($line -match '^\s*Encryption\s+:\s*(.*)$') {
                $enc = $Matches[1].Trim()
                if ($current.Security) {
                    $current.Security = "$($current.Security) / $enc"
                } else {
                    $current.Security = $enc
                }
            } elseif ($line -match '^\s*BSSID\s+\d+\s+:\s*(.*)$') {
                $current.Address = $Matches[1].Trim()
            } elseif ($line -match '^\s*Signal\s+:\s*(.*)$') {
                $current.Strength = $Matches[1].Trim()
            } elseif ($line -match '^\s*Channel\s+:\s*(.*)$') {
                $current.Channel = $Matches[1].Trim()
            }
        }
        if ($current) {
            $wifiRow = [pscustomobject]$current
            $info = Get-WifiSignalExplanation -Wifi $wifiRow
            $wifiRow | Add-Member -NotePropertyName SpecificType -NotePropertyValue $info.SpecificType
            $wifiRow | Add-Member -NotePropertyName Confidence -NotePropertyValue $info.Confidence
            $wifiRow | Add-Member -NotePropertyName Evidence -NotePropertyValue $info.Evidence
            $wifiRow | Add-Member -NotePropertyName Meaning -NotePropertyValue $info.Meaning
            $wifiRow | Add-Member -NotePropertyName NextStep -NotePropertyValue $info.NextStep
            $items += $wifiRow
        }
    } catch {
        $items += [pscustomobject][ordered]@{
            Name = "Wi-Fi scan failed"
            Address = ""
            Strength = ""
            Channel = ""
            Security = ""
            Type = "Wi-Fi"
            Notes = $_.Exception.Message
        }
    }

    return $items
}

function Get-BluetoothDetails {
    try {
        $devices = Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue |
            Sort-Object -Property FriendlyName

        return @($devices | ForEach-Object {
            $row = [pscustomobject][ordered]@{
                Name = if ($_.FriendlyName) { $_.FriendlyName } else { $_.Name }
                Address = $_.InstanceId
                Status = $_.Status
                Class = $_.Class
                Type = "Bluetooth"
                Notes = if ($_.Present) { "Present" } else { "Known device; not currently present" }
            }
            $info = Get-BluetoothSignalExplanation -Device $row
            $row | Add-Member -NotePropertyName SpecificType -NotePropertyValue $info.SpecificType
            $row | Add-Member -NotePropertyName Confidence -NotePropertyValue $info.Confidence
            $row | Add-Member -NotePropertyName Evidence -NotePropertyValue $info.Evidence
            $row | Add-Member -NotePropertyName Meaning -NotePropertyValue $info.Meaning
            $row | Add-Member -NotePropertyName NextStep -NotePropertyValue $info.NextStep
            $row
        })
    } catch {
        return @([pscustomobject][ordered]@{
            Name = "Bluetooth scan failed"
            Address = ""
            Status = ""
            Class = "Bluetooth"
            Type = "Bluetooth"
            Notes = $_.Exception.Message
        })
    }
}

function Get-SdrDetails {
    if ($script:SdrSignals.Count -gt 0) {
        return @($script:SdrSignals)
    }

    return @([pscustomobject][ordered]@{
        Frequency = "No measured SDR detections yet"
        FrequencyHz = ""
        PowerDb = ""
        Bandwidth = ""
        Label = "Run DEEP SCAN"
        Modulation = ""
        PossibleUse = "No RF peaks have been measured above the local noise floor."
        Audio = ""
        Confidence = ""
        Evidence = ""
        Description = "The SDR table only displays rtl_power deep-scan results. Catalog placeholders are hidden so they cannot be mistaken for detections."
        NextStep = "Click DEEP SCAN (rtl_power) to measure the spectrum and show confirmed candidate peaks."
        Source = "idle"
        Decoder = ""
    })
}

function Get-UnavailableDetails {
    param(
        [string] $Name,
        [string] $Reason
    )

    return @([pscustomobject][ordered]@{
        Name = $Name
        Address = ""
        Status = "Unavailable on Windows"
        Type = "Phone hardware"
        SpecificType = $Name
        Confidence = "Hardware unavailable"
        Evidence = "No compatible Windows hardware/API exposed"
        Meaning = $Reason
        NextStep = "Use the Android phone scanner for this section or attach a compatible Windows reader."
        Notes = $Reason
    })
}

function Get-AlertDetails {
    $alerts = @()

    foreach ($wifi in @(Get-WifiDetails)) {
        $alert = Get-SignalAlertClassification -Name $wifi.Name -Type $wifi.Type -SpecificType $wifi.SpecificType -ThreatLevel "" -Notes (Join-NonEmptyText -Values @($wifi.Security, $wifi.Evidence, $wifi.Meaning))
        if ($alert.Level -ne "NONE") {
            $alerts += [pscustomobject][ordered]@{
                Level = $alert.Level
                Name = $wifi.Name
                Address = $wifi.Address
                Strength = $wifi.Strength
                Channel = $wifi.Channel
                Type = "Wi-Fi"
                SpecificType = $wifi.SpecificType
                Confidence = $wifi.Confidence
                Evidence = $alert.Evidence
                Meaning = $alert.Meaning
                NextStep = $alert.NextStep
                Notes = $alert.Notes
            }
        }
    }

    foreach ($profile in @(Get-AwarenessDisplayProfiles -Profiles @(Get-AwarenessProfiles))) {
        if ($profile.Class -eq "Normal") { continue }
        $alert = Get-SignalAlertClassification -Name $profile.Signal -Type $profile.SourceType -SpecificType $profile.Type -ThreatLevel $profile.ThreatLevel -Notes $profile.LastEvent
        if ($alert.Level -eq "NONE") { continue }
        $alerts += [pscustomobject][ordered]@{
            Level = $alert.Level
            Name = $profile.Signal
            Address = $profile.RawIds
            Strength = $profile.Strength
            Channel = ""
            Type = $profile.SourceType
            SpecificType = $profile.Type
            Confidence = $profile.ThreatLevel
            Evidence = $alert.Evidence
            Meaning = $alert.Meaning
            NextStep = $alert.NextStep
            Notes = $alert.Notes
        }
    }

    if ($alerts.Count -gt 0) {
        return @($alerts | Sort-Object -Property @{ Expression = { Get-AlertSortRank $_.Level }; Descending = $false }, Name)
    }

    return @([pscustomobject][ordered]@{
        Level = "CLEAR"
        Name = "ALL CLEAR"
        Address = ""
        Strength = ""
        Channel = ""
        Type = "Alert"
        SpecificType = ""
        Confidence = ""
        Evidence = "No alert-tier classifications matched."
        Meaning = "New or ordinary signals stay in Awareness Timeline and do not become alerts by themselves."
        NextStep = "Review Awareness Timeline for history, one-offs, and changes."
        Notes = "Alerts are reserved for weirdness, surveillance/traffic systems, and data-capture/interception risks."
    })
}

function Get-AlertSortRank {
    param([string] $Level)
    switch (($Level).ToUpperInvariant()) {
        "HIGH" { return 0 }
        "MEDIUM" { return 1 }
        "LOW" { return 2 }
        default { return 9 }
    }
}

function Get-SignalAlertClassification {
    param(
        [string] $Name,
        [string] $Type,
        [string] $SpecificType,
        [string] $ThreatLevel,
        [string] $Notes
    )

    $text = (Join-NonEmptyText -Values @($Name, $Type, $SpecificType, $ThreatLevel, $Notes) -Separator " ").ToLowerInvariant()
    $threat = ([string]$ThreatLevel).ToUpperInvariant()

    $highPattern = '(imsi|stingray|fake\s*sim|fake\s*cell|rogue\s*cell|cell\s*site\s*simulator|evil\s*twin|wifi\s*pineapple|pineapple|deauther|pwnagotchi|marauder|flipper|badusb|skimmer|tap\s*to\s*pay|payment|nfc\s*intercept|credential|password|phish|sniffer|data[- ]?capture|hacking)'
    $mediumPattern = '(flock|flock\s*safety|alpr|lpr|license\s*plate|plate\s*reader|traffic\s*reader|traffic\s*camera|speed\s*camera|red\s*light|surveillance|cctv|doorbell|verkada|avigilon|hikvision|dahua|axis|vigilant|genetec|motorola)'
    $lowPattern = '(unknown\s*ble|beacon|tracker|airtag|tile|hidden\s*wifi|open\s*wifi|open\s*security|unsecured|rogue|spoof|jam|burst|unclassified\s*rf|unexpected|odd|weird)'

    $highMatch = if ($text -match $highPattern) { $Matches[0] } else { "" }
    $mediumMatch = if ($text -match $mediumPattern) { $Matches[0] } else { "" }
    $lowMatch = if ($text -match $lowPattern) { $Matches[0] } else { "" }
    $movementMatch = if ($text -match '(new\s+scan\s+location|location_changed|also\s+seen\s+by|same\s+reader|following|followed|moved\s+with)') { $Matches[0] } else { "" }

    if ($threat -eq "ALERT" -or $highMatch) {
        return [pscustomobject][ordered]@{
            Level = "HIGH"
            Evidence = if ($highMatch) { "High-risk keyword/classification: $highMatch" } else { "Threat level is ALERT" }
            Meaning = "Possible data-capture, impersonation, payment/NFC interception, rogue cellular, or credential-stealing equipment."
            NextStep = "Do not connect or tap credentials/payment devices near it; correlate location and repeat sightings."
            Notes = "High alert: possible data-gathering/interception risk."
        }
    }
    if ($threat -eq "SUSPICIOUS" -or $mediumMatch) {
        if ($movementMatch) {
            return [pscustomobject][ordered]@{
                Level = "HIGH"
                Evidence = "Surveillance/traffic class with movement clue: $movementMatch"
                Meaning = "Possible surveillance or reader system seen across scan locations or nodes."
                NextStep = "Correlate the timeline and map; repeated movement with your route deserves immediate attention."
                Notes = "High alert: surveillance-class signal appears to move or repeat across scan locations."
            }
        }
        return [pscustomobject][ordered]@{
            Level = "MEDIUM"
            Evidence = if ($mediumMatch) { "Surveillance/traffic keyword/classification: $mediumMatch" } else { "Threat level is SUSPICIOUS" }
            Meaning = "Possible Flock, ALPR, traffic reader, camera, or surveillance-style system."
            NextStep = "Correlate with roadway/parking locations, camera hardware, and repeated GPS sightings."
            Notes = "Medium alert: possible surveillance, traffic, or reader system."
        }
    }
    if ($lowMatch) {
        return [pscustomobject][ordered]@{
            Level = "LOW"
            Evidence = "Noticed/weirdness keyword/classification: $lowMatch"
            Meaning = "Something is unusual enough to notice, but it is not classified as data theft or surveillance."
            NextStep = "Let the timeline decide if it becomes normal, repeats in odd places, or changes behavior."
            Notes = "Low alert: weirdness or unusual signal, not merely new."
        }
    }

    return [pscustomobject][ordered]@{
        Level = "NONE"
        Evidence = ""
        Meaning = ""
        NextStep = ""
        Notes = ""
    }
}

function Get-AwarenessDetails {
    $rows = @(Get-AwarenessRows)
    if ($rows.Count -gt 0) { return $rows }

    return @([pscustomobject][ordered]@{
        Type = "Awareness"
        Signal = "No synced signal history yet"
        AddressOrFrequency = ""
        StrengthOrPower = ""
        Classification = "Waiting for nodes"
        Confidence = ""
        Details = "Run the phone app standalone or enable Windows sync from the phone when this PC is reachable."
    })
}

function Join-NonEmptyText {
    param([object[]] $Values, [string] $Separator = "; ")

    return (($Values | ForEach-Object { ([string]$_).Trim() } | Where-Object { $_ }) -join $Separator)
}

function Get-AwarenessProfiles {
    try {
        $state = Read-AwarenessState
        return @($state.Signals.GetEnumerator() | ForEach-Object {
            $profile = $_.Value
            $timeline = @($profile.Timeline)
            $sightings = @($profile.Sightings)
            $lastEvent = if ($timeline.Count -gt 0) { $timeline[-1].Summary } else { "" }
            $alert = Get-SignalAlertClassification -Name $profile.Name -Type $profile.Type -SpecificType $profile.SpecificType -ThreatLevel $profile.ThreatLevel -Notes (Join-NonEmptyText -Values @($lastEvent, $profile.Notes) -Separator " ")
            $presence = if ($profile.PresenceState) { [string]$profile.PresenceState } else { "seen" }
            $class = switch ($alert.Level) {
                "HIGH" { "Alert"; break }
                "MEDIUM" { "Watch"; break }
                "LOW" { if ([int]$profile.SeenCount -ge 5) { "Normal" } else { "Noticed" }; break }
                default {
                    if ([int]$profile.SeenCount -le 1) { "One-off" } else { "Normal" }
                }
            }
            $lastSighting = if ($sightings.Count -gt 0) { $sightings[-1] } else { $null }
            [pscustomobject][ordered]@{
                Key = $_.Key
                Name = if ($profile.Name) { $profile.Name } else { $profile.Key }
                Type = $profile.Type
                SpecificType = $profile.SpecificType
                Address = $profile.Address
                FrequencyHz = $profile.FrequencyHz
                SeenCount = [int]$profile.SeenCount
                NodeCount = @($profile.NodeIds).Count
                LastSignal = $profile.LastSignal
                StrongestSignal = $profile.StrongestSignal
                ThreatLevel = $profile.ThreatLevel
                PresenceState = if ($profile.PresenceState) { $profile.PresenceState } else { "seen" }
                LastSeen = $profile.LastSeen
                EstimatedLatitude = $profile.EstimatedLatitude
                EstimatedLongitude = $profile.EstimatedLongitude
                LastLatitude = if ($lastSighting) { $lastSighting.Latitude } else { $profile.EstimatedLatitude }
                LastLongitude = if ($lastSighting) { $lastSighting.Longitude } else { $profile.EstimatedLongitude }
                TimelineCount = $timeline.Count
                LastEvent = $lastEvent
                Class = $class
                Details = "Seen $($profile.SeenCount)x from $(@($profile.NodeIds).Count) node(s); $lastEvent"
                Timeline = $timeline
                Sightings = $sightings
            }
        } | Sort-Object -Property @{ Expression = "Class"; Descending = $false }, @{ Expression = "SeenCount"; Descending = $true })
    } catch {
        Write-AppError -Context "Read awareness profiles" -ErrorObject $_
        return @()
    }
}

function Get-AwarenessScanLocations {
    $profiles = @(Get-AwarenessDisplayProfiles -Profiles @(Get-AwarenessProfiles))
    $points = @()
    foreach ($profile in $profiles) {
        $seenLocationKeys = @{}
        foreach ($sighting in @($profile.Sightings)) {
            $lat = ConvertTo-AwarenessNumber $sighting.Latitude
            $lon = ConvertTo-AwarenessNumber $sighting.Longitude
            if ($null -eq $lat -or $null -eq $lon) { continue }
            $key = "{0:N4},{1:N4}" -f $lat, $lon
            if ($seenLocationKeys.ContainsKey($key)) { continue }
            $seenLocationKeys[$key] = $true
            $existing = @($points | Where-Object { $_.Key -eq $key } | Select-Object -First 1)
            if ($existing.Count -gt 0) {
                $existing[0].SignalCount++
                if ($profile.Class -ne "Normal") { $existing[0].InterestingCount++ }
            } else {
                $points += [pscustomobject][ordered]@{
                    Key = $key
                    Latitude = $lat
                    Longitude = $lon
                    SignalCount = 1
                    InterestingCount = if ($profile.Class -ne "Normal") { 1 } else { 0 }
                }
            }
        }
    }
    return $points
}

function Get-AwarenessDisplayGroupKey {
    param([object] $Profile)

    $source = ([string]$Profile.Type).Trim().ToUpperInvariant()
    $name = Get-AwarenessDisplayName -Profile $Profile
    $genericNames = @("", "UNKNOWN", "UNCLASSIFIED", "UNCLASSIFIED BLUETOOTH DEVICE OR SERVICE", "UNCLASSIFIED RF SIGNAL")
    $normalizedName = ($name -replace "\s+", " ").Trim().ToUpperInvariant()

    if ($source -notin @("SDR", "RTL_SDR") -and $normalizedName -and $genericNames -notcontains $normalizedName) {
        return "NAME|$source|$normalizedName"
    }

    if ($Profile.Key) { return "KEY|$($Profile.Key)" }
    return "RAW|$source|$normalizedName|$($Profile.Address)|$($Profile.FrequencyHz)"
}

function Get-AwarenessDisplayName {
    param([object] $Profile)

    $name = ([string]$Profile.Name).Trim()
    $source = ([string]$Profile.Type).Trim().ToUpperInvariant()
    if ($source -eq "BLUETOOTH" -and $name) {
        $serviceSuffixes = @(
            "\s+AVRCP\s+TRANSPORT$",
            "\s+A2DP\s+(SINK|SOURCE)$",
            "\s+RFCOMM\s+.*$",
            "\s+HANDS[- ]FREE\s+.*$",
            "\s+HEADSET\s+.*$",
            "\s+GATT\s+.*$",
            "\s+HID\s+.*$"
        )
        foreach ($suffix in $serviceSuffixes) {
            $trimmed = [regex]::Replace($name, $suffix, "", "IgnoreCase").Trim()
            if ($trimmed -and $trimmed -ne $name) { return $trimmed }
        }
    }
    return $name
}

function Get-AwarenessClassRank {
    param([string] $Class)

    switch ($Class) {
        "Alert" { return 5 }
        "Watch" { return 4 }
        "Noticed" { return 3 }
        "One-off" { return 3 }
        "Learning" { return 2 }
        "Normal" { return 1 }
        default { return 0 }
    }
}

function Join-AwarenessUniqueText {
    param([object[]] $Values, [string] $Separator = ", ")

    return (($Values | ForEach-Object { ([string]$_).Trim() } | Where-Object { $_ } | Select-Object -Unique) -join $Separator)
}

function Get-AwarenessDisplayProfiles {
    param([object[]] $Profiles)

    $groups = [ordered]@{}
    foreach ($profile in @($Profiles)) {
        $key = Get-AwarenessDisplayGroupKey -Profile $profile
        if (-not $groups.Contains($key)) { $groups[$key] = @() }
        $groups[$key] = @($groups[$key]) + $profile
    }

    $rows = @()
    foreach ($key in $groups.Keys) {
        $members = @($groups[$key])
        if ($members.Count -eq 0) { continue }

        $primary = @($members | Sort-Object -Property @{ Expression = { Get-AwarenessClassRank -Class $_.Class }; Descending = $true }, @{ Expression = "LastSeen"; Descending = $true } | Select-Object -First 1)[0]
        $latest = @($members | Sort-Object -Property LastSeen -Descending | Select-Object -First 1)[0]
        $timeline = @($members | ForEach-Object { @($_.Timeline) })
        $sightings = @($members | ForEach-Object { @($_.Sightings) })
        $nodeIds = @($sightings | ForEach-Object { [string]$_.NodeId } | Where-Object { $_ } | Select-Object -Unique)
        if ($nodeIds.Count -eq 0) {
            $nodeIds = @($members | ForEach-Object { "node-$($_.NodeCount)" } | Where-Object { $_ } | Select-Object -Unique)
        }
        $latestEvent = if ($latest.LastEvent) { $latest.LastEvent } else { "profile updated" }
        $rawIds = Join-AwarenessUniqueText -Values @($members | ForEach-Object {
            if ($_.Address) { $_.Address } elseif ($_.FrequencyHz) { $_.FrequencyHz } else { $_.Key }
        })
        $types = Join-AwarenessUniqueText -Values @($members | ForEach-Object { $_.SpecificType })

        $rows += [pscustomobject][ordered]@{
            Class = $primary.Class
            Signal = Get-AwarenessDisplayName -Profile $primary
            Type = if ($types) { $types } else { $primary.SpecificType }
            SourceType = $primary.Type
            ThreatLevel = $primary.ThreatLevel
            Seen = (@($members | Measure-Object -Property SeenCount -Sum).Sum)
            Nodes = [Math]::Max($primary.NodeCount, $nodeIds.Count)
            Last = $latest.LastSeen
            LastEvent = if ($members.Count -gt 1) { "Grouped $($members.Count) matching IDs; $latestEvent" } else { $latestEvent }
            Strength = $latest.LastSignal
            RawIds = $rawIds
            CombinedProfiles = $members.Count
            TimelineCount = @($timeline).Count
            Sightings = $sightings
        }
    }

    return @($rows | Sort-Object -Property @{ Expression = { Get-AwarenessClassRank -Class $_.Class }; Descending = $true }, @{ Expression = "Seen"; Descending = $true }, @{ Expression = "Last"; Descending = $true })
}

function Show-AwarenessLocationWindow {
    $locations = @(Get-AwarenessScanLocations)
    if ($locations.Count -eq 0) {
        Show-AwarenessTimelineWindow
        return
    }

    $rows = @()
    foreach ($loc in $locations) {
        $rows += [pscustomobject][ordered]@{
            Location = $loc.Key
            Signals = $loc.SignalCount
            WatchOrOneOff = $loc.InterestingCount
            Notes = "Double-click to view condensed signals from this scan spot"
            LocationKey = $loc.Key
        }
    }

    Show-DetailWindow -Title "Awareness Locations" -Accent "#22D3EE" -Items $rows
}

function Update-AwarenessMapPanel {
    if (-not $AwarenessMapCanvas) { return }

    $profiles = @(Get-AwarenessDisplayProfiles -Profiles @(Get-AwarenessProfiles))
    $locations = @(Get-AwarenessScanLocations)
    $normal = @($profiles | Where-Object { $_.Class -eq "Normal" }).Count
    $oneOff = @($profiles | Where-Object { $_.Class -in @("One-off", "Noticed", "Watch", "Alert") }).Count
    $changes = @($profiles | Where-Object { $_.TimelineCount -gt 1 }).Count

    $AwarenessMapSummary.Text = "$($profiles.Count) known  /  $($locations.Count) scan spots"
    $AwarenessMapNormal.Text = "Normal: $normal"
    $AwarenessMapOdd.Text = "Noticed / changes: $oneOff / $changes"
    $latest = @($profiles | Sort-Object LastSeen -Descending | Select-Object -First 1)
    $AwarenessMapLast.Text = if ($latest.Count -gt 0) { "Latest: $($latest[0].Name) - $($latest[0].Class)" } else { "Click for timeline" }

    $AwarenessMapCanvas.Children.Clear()
    Draw-AwarenessMapGrid
    if ($locations.Count -eq 0) {
        Add-AwarenessMapText -Text "No GPS scan dots yet" -X 18 -Y 42 -Color "#637082" -Size 13
        Add-AwarenessMapText -Text "Sync phone GPS to populate" -X 18 -Y 62 -Color "#637082" -Size 11
        return
    }

    $minLat = ($locations | Measure-Object Latitude -Minimum).Minimum
    $maxLat = ($locations | Measure-Object Latitude -Maximum).Maximum
    $minLon = ($locations | Measure-Object Longitude -Minimum).Minimum
    $maxLon = ($locations | Measure-Object Longitude -Maximum).Maximum
    if ($maxLat -eq $minLat) { $maxLat += 0.001; $minLat -= 0.001 }
    if ($maxLon -eq $minLon) { $maxLon += 0.001; $minLon -= 0.001 }
    $width = [Math]::Max(220.0, $AwarenessMapCanvas.ActualWidth)
    $height = [Math]::Max(110.0, $AwarenessMapCanvas.ActualHeight)

    foreach ($loc in $locations) {
        $x = 16 + (($loc.Longitude - $minLon) / ($maxLon - $minLon)) * ($width - 32)
        $y = 16 + (($maxLat - $loc.Latitude) / ($maxLat - $minLat)) * ($height - 32)
        $radius = [Math]::Min(14, 5 + [Math]::Sqrt($loc.SignalCount))
        $dot = New-Object System.Windows.Shapes.Ellipse
        $dot.Width = $radius * 2
        $dot.Height = $radius * 2
        $dot.Fill = $script:BrushConverter.ConvertFromString($(if ($loc.InterestingCount -gt 0) { "#F59E0B" } else { "#21F982" }))
        $dot.Stroke = $script:BrushConverter.ConvertFromString("#E5E7EB")
        $dot.StrokeThickness = 1
        $dot.ToolTip = "$($loc.SignalCount) signal(s), $($loc.InterestingCount) one-off/change at $($loc.Key)"
        $dot.Tag = $loc.Key
        $dot.Add_MouseLeftButtonUp({
            param($sender, $eventArgs)
            Show-AwarenessTimelineWindow -LocationKey ([string]$sender.Tag)
            $eventArgs.Handled = $true
        })
        [System.Windows.Controls.Canvas]::SetLeft($dot, $x - $radius)
        [System.Windows.Controls.Canvas]::SetTop($dot, $y - $radius)
        [void]$AwarenessMapCanvas.Children.Add($dot)
    }
}

function Draw-AwarenessMapGrid {
    $width = [Math]::Max(220.0, $AwarenessMapCanvas.ActualWidth)
    $height = [Math]::Max(110.0, $AwarenessMapCanvas.ActualHeight)
    for ($i = 1; $i -le 3; $i++) {
        $x = ($width / 4) * $i
        $line = New-Object System.Windows.Shapes.Line
        $line.X1 = $x; $line.X2 = $x; $line.Y1 = 0; $line.Y2 = $height
        $line.Stroke = $script:BrushConverter.ConvertFromString("#143B46")
        $line.StrokeThickness = 1
        [void]$AwarenessMapCanvas.Children.Add($line)
    }
    for ($i = 1; $i -le 2; $i++) {
        $y = ($height / 3) * $i
        $line = New-Object System.Windows.Shapes.Line
        $line.X1 = 0; $line.X2 = $width; $line.Y1 = $y; $line.Y2 = $y
        $line.Stroke = $script:BrushConverter.ConvertFromString("#143B46")
        $line.StrokeThickness = 1
        [void]$AwarenessMapCanvas.Children.Add($line)
    }
}

function Add-AwarenessMapText {
    param([string] $Text, [double] $X, [double] $Y, [string] $Color, [double] $Size)

    $tb = New-Object System.Windows.Controls.TextBlock
    $tb.Text = $Text
    $tb.Foreground = $script:BrushConverter.ConvertFromString($Color)
    $tb.FontFamily = "Consolas"
    $tb.FontSize = $Size
    [System.Windows.Controls.Canvas]::SetLeft($tb, $X)
    [System.Windows.Controls.Canvas]::SetTop($tb, $Y)
    [void]$AwarenessMapCanvas.Children.Add($tb)
}

function Show-AwarenessTimelineWindow {
    param([string] $LocationKey = "")

    $profiles = @(Get-AwarenessProfiles)
    if ($LocationKey) {
        $profiles = @($profiles | Where-Object {
            @($_.Sightings | Where-Object {
                $lat = ConvertTo-AwarenessNumber $_.Latitude
                $lon = ConvertTo-AwarenessNumber $_.Longitude
                $key = if ($null -ne $lat -and $null -ne $lon) { "{0:N4},{1:N4}" -f $lat, $lon } else { "" }
                $key -eq $LocationKey
            }).Count -gt 0
        })
    }

    $rows = @()
    foreach ($profile in @(Get-AwarenessDisplayProfiles -Profiles $profiles)) {
        $rows += [pscustomobject][ordered]@{
            Class = $profile.Class
            Signal = $profile.Signal
            Type = $profile.Type
            Seen = $profile.Seen
            Nodes = $profile.Nodes
            Last = $profile.Last
            LastEvent = $profile.LastEvent
            Strength = $profile.Strength
            RawIds = $profile.RawIds
            CombinedProfiles = $profile.CombinedProfiles
        }
    }
    if ($rows.Count -eq 0) {
        $rows = @([pscustomobject][ordered]@{
            Class = "Empty"
            Signal = "No awareness records for this view"
            Type = ""
            Seen = ""
            Nodes = ""
            Last = ""
            LastEvent = ""
            Strength = ""
        })
    }
    $title = if ($LocationKey) { "Awareness Timeline - $LocationKey" } else { "Awareness Timeline" }
    Show-DetailWindow -Title $title -Accent "#22D3EE" -Items $rows
}

function Sync-LocalAwarenessSnapshot {
    try {
        $signals = @()
        foreach ($wifi in @(Get-WifiDetails)) {
            if ($wifi.Name -match "failed") { continue }
            $signals += [pscustomobject][ordered]@{
                id = "windows_wifi_$($wifi.Address)"
                name = $wifi.Name
                address = $wifi.Address
                type = "WIFI"
                deviceClass = $wifi.SpecificType
                manufacturer = ""
                threatLevel = "UNKNOWN"
                signalStrength = $wifi.Strength
                channel = $wifi.Channel
                frequencyHz = ""
                notes = Join-NonEmptyText -Values @($wifi.Security, $wifi.Evidence)
            }
        }
        foreach ($bt in @(Get-BluetoothDetails)) {
            if ($bt.Name -match "failed") { continue }
            $signals += [pscustomobject][ordered]@{
                id = "windows_bt_$($bt.Address)"
                name = $bt.Name
                address = $bt.Address
                type = "BLUETOOTH"
                deviceClass = $bt.SpecificType
                manufacturer = ""
                threatLevel = "UNKNOWN"
                signalStrength = $bt.Status
                channel = ""
                frequencyHz = ""
                notes = Join-NonEmptyText -Values @($bt.Class, $bt.Notes, $bt.Evidence)
            }
        }
        foreach ($sdr in @($script:SdrSignals | Where-Object { $_.Source -eq "rtl_power" })) {
            $signals += [pscustomobject][ordered]@{
                id = "windows_sdr_$($sdr.FrequencyHz)"
                name = $sdr.Label
                address = ""
                type = "RTL_SDR"
                deviceClass = $sdr.PossibleUse
                manufacturer = ""
                threatLevel = "UNKNOWN"
                signalStrength = $sdr.PowerDb
                channel = ""
                frequencyHz = $sdr.FrequencyHz
                notes = Join-NonEmptyText -Values @($sdr.Modulation, $sdr.Evidence, $sdr.Source)
            }
        }

        $completeTypes = @()
        if ($script:SdrPowerScanCompleted) { $completeTypes += "RTL_SDR" }
        if ($signals.Count -eq 0 -and $completeTypes.Count -eq 0) { return $null }
        return Merge-AwarenessSnapshot -Snapshot ([pscustomobject][ordered]@{
            nodeId = "windows-$env:COMPUTERNAME"
            nodeName = "Windows $env:COMPUTERNAME"
            location = [pscustomobject]@{}
            completeTypes = $completeTypes
            signals = $signals
        })
    } catch {
        Write-AppError -Context "Local awareness sync" -ErrorObject $_
        return $null
    }
}

function Get-MainSignalRows {
    $rows = @()

    foreach ($wifi in @(Get-WifiDetails)) {
        $rows += [pscustomobject][ordered]@{
            Type = "Wi-Fi"
            Signal = $wifi.Name
            AddressOrFrequency = $wifi.Address
            StrengthOrPower = $wifi.Strength
            Classification = $wifi.SpecificType
            Confidence = $wifi.Confidence
            Details = Join-NonEmptyText -Values @("Ch $($wifi.Channel)", $wifi.Security, $wifi.Evidence)
        }
    }

    foreach ($bt in @(Get-BluetoothDetails)) {
        $rows += [pscustomobject][ordered]@{
            Type = "Bluetooth"
            Signal = $bt.Name
            AddressOrFrequency = $bt.Address
            StrengthOrPower = $bt.Status
            Classification = $bt.SpecificType
            Confidence = $bt.Confidence
            Details = Join-NonEmptyText -Values @($bt.Class, $bt.Notes, $bt.Evidence)
        }
    }

    foreach ($sdr in @($script:SdrSignals)) {
        if ($sdr.Label -eq "Error") { continue }
        $rows += [pscustomobject][ordered]@{
            Type = "SDR"
            Signal = $sdr.Label
            AddressOrFrequency = $sdr.Frequency
            StrengthOrPower = "$($sdr.PowerDb) dB"
            Classification = $sdr.PossibleUse
            Confidence = $sdr.Confidence
            Details = Join-NonEmptyText -Values @($sdr.Modulation, $sdr.Audio, $sdr.Evidence)
        }
    }

    foreach ($known in @(Get-AwarenessRows)) {
        $rows += [pscustomobject][ordered]@{
            Type = "Awareness"
            Signal = $known.Signal
            AddressOrFrequency = $known.AddressOrFrequency
            StrengthOrPower = $known.StrengthOrPower
            Classification = $known.Classification
            Confidence = $known.Confidence
            Details = $known.Details
        }
    }

    if ($rows.Count -eq 0) {
        $rows += [pscustomobject][ordered]@{
            Type = "Status"
            Signal = "No signals listed yet"
            AddressOrFrequency = ""
            StrengthOrPower = ""
            Classification = ""
            Confidence = ""
            Details = "Click REFRESH or open SDR Radio to run an SDR sweep."
        }
    }

    return $rows
}

function Get-ObjectDetailRows {
    param([object] $Item)

    if (-not $Item) { return @() }

    $preferred = @(
        "Name", "Signal", "SpecificType", "Classification", "Type",
        "Address", "AddressOrFrequency", "Frequency", "FrequencyHz",
        "Strength", "StrengthOrPower", "PowerDb", "Channel", "Security",
        "Status", "Class", "Modulation", "Bandwidth", "Decoder", "Source",
        "Confidence", "Evidence", "Meaning", "Description", "NextStep",
        "PossibleUse", "Audio", "Notes", "Details"
    )

    $props = @($Item.PSObject.Properties | Where-Object {
        $_.MemberType -match "Property" -and -not [string]::IsNullOrWhiteSpace([string]$_.Value)
    })

    $ordered = @()
    foreach ($name in $preferred) {
        $match = @($props | Where-Object { $_.Name -eq $name } | Select-Object -First 1)
        if ($match.Count -gt 0) { $ordered += $match[0] }
    }
    foreach ($prop in $props) {
        if (-not ($ordered | Where-Object { $_.Name -eq $prop.Name })) { $ordered += $prop }
    }

    return @($ordered | ForEach-Object {
        [pscustomobject][ordered]@{
            Field = $_.Name
            Value = [string]$_.Value
        }
    })
}

function New-DataGridTextStyle {
    param([bool] $Wrap = $false)

    $style = [System.Windows.Style]::new([System.Windows.Controls.TextBlock])
    [void]$style.Setters.Add([System.Windows.Setter]::new([System.Windows.Controls.TextBlock]::PaddingProperty, [System.Windows.Thickness]::new(4, 1, 4, 1)))
    if ($Wrap) {
        [void]$style.Setters.Add([System.Windows.Setter]::new([System.Windows.Controls.TextBlock]::TextWrappingProperty, [System.Windows.TextWrapping]::Wrap))
    } else {
        [void]$style.Setters.Add([System.Windows.Setter]::new([System.Windows.Controls.TextBlock]::TextTrimmingProperty, [System.Windows.TextTrimming]::CharacterEllipsis))
    }
    return $style
}

function Show-SignalDetailWindow {
    param(
        [string] $Title,
        [string] $Accent,
        [object] $Item
    )

    if (-not $Item) { return }

    $detailWindow = New-Object System.Windows.Window
    Set-SnifferOpsWindowIcon -TargetWindow $detailWindow
    $detailWindow.Title = "SnifferOps - Signal Details"
    $detailWindow.Width = 780
    $detailWindow.Height = 520
    $detailWindow.MinWidth = 520
    $detailWindow.MinHeight = 360
    $detailWindow.Background = $script:BrushConverter.ConvertFromString("#020617")
    $detailWindow.WindowStartupLocation = "CenterOwner"
    $detailWindow.Owner = $Window

    $root = New-Object System.Windows.Controls.DockPanel
    $root.Margin = "16"

    $header = New-Object System.Windows.Controls.TextBlock
    $name = if ($Item.Name) { [string]$Item.Name } elseif ($Item.Signal) { [string]$Item.Signal } elseif ($Item.Frequency) { [string]$Item.Frequency } else { $Title }
    $kind = if ($Item.SpecificType) { [string]$Item.SpecificType } elseif ($Item.Classification) { [string]$Item.Classification } elseif ($Item.Label) { [string]$Item.Label } else { [string]$Item.Type }
    $header.Text = (Join-NonEmptyText -Values @($name, $kind) -Separator " - ").ToUpperInvariant()
    $header.Foreground = $script:BrushConverter.ConvertFromString($Accent)
    $header.FontFamily = "Consolas"
    $header.FontSize = 20
    $header.FontWeight = "Bold"
    $header.Margin = "0,0,0,12"
    [System.Windows.Controls.DockPanel]::SetDock($header, "Top")
    [void]$root.Children.Add($header)

    $grid = New-Object System.Windows.Controls.DataGrid
    $grid.AutoGenerateColumns = $false
    $grid.IsReadOnly = $true
    $grid.CanUserAddRows = $false
    $grid.CanUserDeleteRows = $false
    $grid.GridLinesVisibility = "Horizontal"
    $grid.Background = $script:BrushConverter.ConvertFromString("#0B1120")
    $grid.Foreground = $script:BrushConverter.ConvertFromString("#E5E7EB")
    $grid.RowBackground = $script:BrushConverter.ConvertFromString("#111827")
    $grid.AlternatingRowBackground = $script:BrushConverter.ConvertFromString("#0F172A")
    $grid.BorderBrush = $script:BrushConverter.ConvertFromString("#374151")
    $grid.FontFamily = "Consolas"
    $grid.FontSize = 12
    $grid.HorizontalAlignment = "Stretch"
    $grid.VerticalAlignment = "Stretch"
    $grid.HorizontalScrollBarVisibility = "Disabled"

    $fieldColumn = New-Object System.Windows.Controls.DataGridTextColumn
    $fieldColumn.Header = "Field"
    $fieldColumn.Binding = New-Object System.Windows.Data.Binding("Field")
    $fieldColumn.Width = New-Object System.Windows.Controls.DataGridLength(145)
    $fieldColumn.ElementStyle = New-DataGridTextStyle
    [void]$grid.Columns.Add($fieldColumn)

    $valueColumn = New-Object System.Windows.Controls.DataGridTextColumn
    $valueColumn.Header = "Value"
    $valueColumn.Binding = New-Object System.Windows.Data.Binding("Value")
    $valueColumn.Width = New-Object System.Windows.Controls.DataGridLength(1, [System.Windows.Controls.DataGridLengthUnitType]::Star)
    $valueColumn.ElementStyle = New-DataGridTextStyle -Wrap $true
    [void]$grid.Columns.Add($valueColumn)

    $grid.ItemsSource = @(Get-ObjectDetailRows -Item $Item)
    [void]$root.Children.Add($grid)

    $detailWindow.Content = $root
    Apply-SnifferOpsFont -Root $detailWindow
    Apply-SnifferOpsSpecialFonts -Root $detailWindow
    [void]$detailWindow.ShowDialog()
}

function Get-CompactDetailColumns {
    param([string] $Title)

    switch ($Title) {
        "WiFi Scanner" {
            return @(
                @{ Name = "Name"; Header = "Name" },
                @{ Name = "SpecificType"; Header = "Type*" },
                @{ Name = "Strength"; Header = "Signal" },
                @{ Name = "Address"; Header = "ID / BSSID" },
                @{ Name = "Channel"; Header = "Channel" },
                @{ Name = "Security"; Header = "Security" }
            )
        }
        "Bluetooth Scanner" {
            return @(
                @{ Name = "Name"; Header = "Name" },
                @{ Name = "SpecificType"; Header = "Type*" },
                @{ Name = "Status"; Header = "Signal" },
                @{ Name = "Address"; Header = "ID" },
                @{ Name = "Notes"; Header = "Notes" }
            )
        }
        "SDR Radio" {
            return @(
                @{ Name = "Frequency"; Header = "Frequency" },
                @{ Name = "Label"; Header = "Type*" },
                @{ Name = "PowerDb"; Header = "Measured dB" },
                @{ Name = "Modulation"; Header = "Mode" },
                @{ Name = "Decoder"; Header = "Lens" },
                @{ Name = "Source"; Header = "Source" }
            )
        }
        { $_ -like "Awareness Timeline*" } {
            return @(
                @{ Name = "Class"; Header = "Status" },
                @{ Name = "Signal"; Header = "Signal" },
                @{ Name = "Type"; Header = "Type*" },
                @{ Name = "Seen"; Header = "Seen" },
                @{ Name = "Nodes"; Header = "Nodes" },
                @{ Name = "Last"; Header = "Last seen" },
                @{ Name = "LastEvent"; Header = "Latest timeline note" },
                @{ Name = "Strength"; Header = "Signal" }
            )
        }
        "Awareness Locations" {
            return @(
                @{ Name = "Location"; Header = "Scan spot" },
                @{ Name = "Signals"; Header = "Signals" },
                @{ Name = "WatchOrOneOff"; Header = "Noticed / watch" },
                @{ Name = "Notes"; Header = "Next" }
            )
        }
        "Signal Alerts + Awareness" {
            return @(
                @{ Name = "Level"; Header = "Level" },
                @{ Name = "Name"; Header = "Signal" },
                @{ Name = "SpecificType"; Header = "Type*" },
                @{ Name = "Type"; Header = "Source" },
                @{ Name = "Strength"; Header = "Signal" },
                @{ Name = "Evidence"; Header = "Why" },
                @{ Name = "Notes"; Header = "Tier" }
            )
        }
        default {
            return @(
                @{ Name = "Name"; Header = "Name" },
                @{ Name = "SpecificType"; Header = "Type*" },
                @{ Name = "Status"; Header = "Status" },
                @{ Name = "Address"; Header = "ID" },
                @{ Name = "Notes"; Header = "Notes" }
            )
        }
    }
}

function Stop-SdrAudio {
    param([bool] $RestoreServer = $true)

    try {
        if ($script:AudioStreamer) {
            $script:AudioStreamer.Stop()
            $err = $script:AudioStreamer.ErrorText
            $script:AudioStreamer.Dispose()
            $script:AudioStreamer = $null
            if (-not [string]::IsNullOrWhiteSpace($err)) {
                Add-LogLine "rtl_fm: $err"
            }
        }

        if ($RestoreServer -and $script:RestartRtlTcpAfterListen) {
            $script:RestartRtlTcpAfterListen = $false
            Start-RtlTcpServer
        }
    } catch {
        Write-AppError -Context "Stop SDR audio" -ErrorObject $_
    }
}

# --- Direct FM/AM radio tuner ----------------------------------------------
# Drives rtl_fm.exe straight to the dongle and plays its raw 16-bit PCM stdout
# through PcmWaveStreamer (winmm). This is a known-good demod chain, separate
# from the in-process rtl_tcp demodulator, so it doubles as an audio sanity test.
# rtl_fm needs exclusive dongle access, so rtl_tcp is paused while tuning.

# Returns the rtl_fm arguments and the PCM sample rate for a given mode.
function Get-TunerConfig {
    param([long] $FrequencyHz, [string] $Mode, [string] $Gain)

    $gainArg = if ([string]::IsNullOrWhiteSpace($Gain) -or $Gain -eq "auto") { "" } else { " -g $Gain" }
    switch ($Mode) {
        "FM" {
            # Wideband broadcast FM: 200k sample, 48k audio out, 75us de-emphasis.
            return [pscustomobject]@{
                Args = "-f $FrequencyHz -M wbfm -s 200000 -r 48000 -E deemp$gainArg -"
                SampleRate = 48000
            }
        }
        "AM" {
            # Narrow AM (aviation / shortwave voice): 24k audio out.
            return [pscustomobject]@{
                Args = "-f $FrequencyHz -M am -s 24000 -r 24000$gainArg -"
                SampleRate = 24000
            }
        }
        "NFM" {
            # Narrowband FM (ham / business / weather): 24k audio out.
            return [pscustomobject]@{
                Args = "-f $FrequencyHz -M fm -s 24000 -r 24000$gainArg -"
                SampleRate = 24000
            }
        }
        default {
            return [pscustomobject]@{
                Args = "-f $FrequencyHz -M wbfm -s 200000 -r 48000 -E deemp$gainArg -"
                SampleRate = 48000
            }
        }
    }
}

function Stop-RadioTuner {
    try {
        if ($script:TunerStreamer) {
            $script:TunerStreamer.Stop()
            $err = $script:TunerStreamer.ErrorText
            $script:TunerStreamer.Dispose()
            $script:TunerStreamer = $null
            if (-not [string]::IsNullOrWhiteSpace($err)) {
                Add-LogLine "rtl_fm: $err"
            }
        }
        if ($script:TunerRestartRtlTcp) {
            $script:TunerRestartRtlTcp = $false
            Start-RtlTcpServer
        }
    } catch {
        Write-AppError -Context "Stop radio tuner" -ErrorObject $_
    }
}

function Start-RadioTuner {
    param([long] $FrequencyHz, [string] $Mode, [string] $Gain = $script:DefaultTunerGain)

    if (-not (Test-Path $RtlFmPath)) {
        Add-LogLine "Missing rtl_fm.exe in $ToolRoot."
        return "rtl_fm.exe not found"
    }
    if ($FrequencyHz -le 0) { return "Enter a valid frequency" }

    # Stop any existing tuner stream (but don't bounce rtl_tcp twice).
    if ($script:TunerStreamer) {
        $script:TunerStreamer.Stop()
        $script:TunerStreamer.Dispose()
        $script:TunerStreamer = $null
    }

    if (Get-Process rtl_tcp -ErrorAction SilentlyContinue) {
        Add-LogLine "Pausing rtl_tcp so the tuner can use the dongle..."
        Get-Process rtl_tcp -ErrorAction SilentlyContinue | Stop-Process -Force
        Start-Sleep -Milliseconds 400
        $script:TunerRestartRtlTcp = $true
    }

    $cfg = Get-TunerConfig -FrequencyHz $FrequencyHz -Mode $Mode -Gain $Gain
    $script:TunerStreamer = New-Object PcmWaveStreamer
    $script:TunerStreamer.Start($RtlFmPath, $cfg.Args, $ToolRoot, $cfg.SampleRate)
    Start-Sleep -Milliseconds 500

    $err = $script:TunerStreamer.ErrorText
    if (-not [string]::IsNullOrWhiteSpace($err)) {
        Add-LogLine "rtl_fm error: $err"
        return $err
    }

    Add-LogLine "Tuner ON: $(Format-Frequency -Frequency $FrequencyHz) [$Mode]"
    return ""
}

function Show-RadioTunerWindow {
    $win = New-Object System.Windows.Window
    Set-SnifferOpsWindowIcon -TargetWindow $win
    $win.Title = "SnifferOps - FM/AM Radio Tuner"
    $win.Width = 440
    $win.SizeToContent = "Height"
    $win.ResizeMode = "NoResize"
    $win.Background = $script:BrushConverter.ConvertFromString("#020617")
    $win.WindowStartupLocation = "CenterOwner"
    $win.Owner = $Window

    $stack = New-Object System.Windows.Controls.StackPanel
    $stack.Margin = "18"

    $title = New-Object System.Windows.Controls.TextBlock
    $title.Text = "RADIO TUNER"
    $title.Foreground = $script:BrushConverter.ConvertFromString("#10B981")
    $title.FontFamily = "Consolas"; $title.FontSize = 20; $title.FontWeight = "Bold"
    $title.Margin = "0,0,0,4"
    [void]$stack.Children.Add($title)

    $hint = New-Object System.Windows.Controls.TextBlock
    $hint.Text = "Tune straight to a station to confirm the dongle produces audio. Pauses the network SDR while playing."
    $hint.Foreground = $script:BrushConverter.ConvertFromString("#9CA3AF")
    $hint.FontFamily = "Consolas"; $hint.FontSize = 11; $hint.TextWrapping = "Wrap"
    $hint.Margin = "0,0,0,14"
    [void]$stack.Children.Add($hint)

    # Frequency row (MHz)
    $freqLabel = New-Object System.Windows.Controls.TextBlock
    $freqLabel.Text = "FREQUENCY (MHz)"
    $freqLabel.Foreground = $script:BrushConverter.ConvertFromString("#E5E7EB")
    $freqLabel.FontFamily = "Consolas"; $freqLabel.FontSize = 12
    [void]$stack.Children.Add($freqLabel)

    $freqBox = New-Object System.Windows.Controls.TextBox
    $freqBox.Text = "92.5"
    $freqBox.FontFamily = "Consolas"; $freqBox.FontSize = 22; $freqBox.FontWeight = "Bold"
    $freqBox.Background = $script:BrushConverter.ConvertFromString("#0B1120")
    $freqBox.Foreground = $script:BrushConverter.ConvertFromString("#10B981")
    $freqBox.BorderBrush = $script:BrushConverter.ConvertFromString("#374151")
    $freqBox.Padding = "8"; $freqBox.Margin = "0,4,0,12"
    [void]$stack.Children.Add($freqBox)

    # Mode row
    $modeLabel = New-Object System.Windows.Controls.TextBlock
    $modeLabel.Text = "MODE"
    $modeLabel.Foreground = $script:BrushConverter.ConvertFromString("#E5E7EB")
    $modeLabel.FontFamily = "Consolas"; $modeLabel.FontSize = 12
    [void]$stack.Children.Add($modeLabel)

    $modeBox = New-Object System.Windows.Controls.ComboBox
    $modeBox.FontFamily = "Consolas"; $modeBox.FontSize = 14; $modeBox.Margin = "0,4,0,12"
    foreach ($m in @("FM (broadcast)", "AM", "NFM (narrowband)")) { [void]$modeBox.Items.Add($m) }
    $modeBox.SelectedIndex = 0
    [void]$stack.Children.Add($modeBox)

    # Gain row. "auto" lets the tuner AGC hunt (pumping); a fixed value is steadier.
    # With a good antenna near strong FM transmitters, LOWER gain avoids front-end
    # overload. Slider re-applies on release so you can sweep while moving antenna.
    $gainLabel = New-Object System.Windows.Controls.TextBlock
    $gainLabel.Foreground = $script:BrushConverter.ConvertFromString("#E5E7EB")
    $gainLabel.FontFamily = "Consolas"; $gainLabel.FontSize = 12
    [void]$stack.Children.Add($gainLabel)

    $gainSlider = New-Object System.Windows.Controls.Slider
    $gainSlider.Minimum = 0; $gainSlider.Maximum = 49; $gainSlider.SmallChange = 1; $gainSlider.LargeChange = 5
    $gainSlider.TickFrequency = 1; $gainSlider.IsSnapToTickEnabled = $true
    $gainSlider.Value = [double]$script:DefaultTunerGain
    $gainSlider.Margin = "0,4,0,12"
    $gainLabel.Text = "GAIN: $([int]$gainSlider.Value) dB"
    [void]$stack.Children.Add($gainSlider)

    $gainSlider.Add_ValueChanged({
        $gainLabel.Text = "GAIN: $([int]$gainSlider.Value) dB"
    }.GetNewClosure())

    # Buttons
    $btnRow = New-Object System.Windows.Controls.StackPanel
    $btnRow.Orientation = "Horizontal"; $btnRow.Margin = "0,0,0,10"

    $tuneBtn = New-Object System.Windows.Controls.Button
    $tuneBtn.Content = "TUNE / PLAY"; $tuneBtn.Width = 180; $tuneBtn.Height = 44
    $tuneBtn.Background = $script:BrushConverter.ConvertFromString("#059669")
    $tuneBtn.Foreground = $script:BrushConverter.ConvertFromString("White")
    $tuneBtn.BorderThickness = 0; $tuneBtn.FontFamily = "Consolas"; $tuneBtn.FontWeight = "Bold"
    [void]$btnRow.Children.Add($tuneBtn)

    $stopBtn = New-Object System.Windows.Controls.Button
    $stopBtn.Content = "STOP"; $stopBtn.Width = 110; $stopBtn.Height = 44; $stopBtn.Margin = "10,0,0,0"
    $stopBtn.Background = $script:BrushConverter.ConvertFromString("#EF4444")
    $stopBtn.Foreground = $script:BrushConverter.ConvertFromString("White")
    $stopBtn.BorderThickness = 0; $stopBtn.FontFamily = "Consolas"; $stopBtn.FontWeight = "Bold"
    [void]$btnRow.Children.Add($stopBtn)
    [void]$stack.Children.Add($btnRow)

    $status = New-Object System.Windows.Controls.TextBlock
    $status.Text = "Idle."
    $status.Foreground = $script:BrushConverter.ConvertFromString("#9CA3AF")
    $status.FontFamily = "Consolas"; $status.FontSize = 12; $status.TextWrapping = "Wrap"
    [void]$stack.Children.Add($status)

    $tuneBtn.Add_Click({
        Invoke-AppAction -Context "Tune radio" -Action {
            $mhz = 0.0
            if (-not [double]::TryParse(($freqBox.Text -replace '[^0-9\.]', ''), [ref]$mhz) -or $mhz -le 0) {
                $status.Text = "Enter a valid frequency in MHz (e.g. 92.5)."
                return
            }
            $hz = [long]($mhz * 1000000)
            $mode = switch ($modeBox.SelectedIndex) { 1 { "AM" } 2 { "NFM" } default { "FM" } }
            $gain = "$([int]$gainSlider.Value)"
            $status.Text = "Tuning $mhz MHz [$mode] @ ${gain}dB..."
            $err = Start-RadioTuner -FrequencyHz $hz -Mode $mode -Gain $gain
            if ([string]::IsNullOrWhiteSpace($err)) {
                $status.Text = "PLAYING $mhz MHz [$mode] @ ${gain}dB. Drag GAIN and release to re-tune. With a big antenna near strong FM, try LOWER gain to cut overload."
            } else {
                $status.Text = "Error: $err"
            }
        }
    }.GetNewClosure())

    # Re-apply gain live when the slider is released (drag end or click).
    $gainSlider.Add_PreviewMouseUp({
        if (-not $script:TunerStreamer) { return }
        Invoke-AppAction -Context "Adjust tuner gain" -Action {
            $mhz = 0.0
            if (-not [double]::TryParse(($freqBox.Text -replace '[^0-9\.]', ''), [ref]$mhz) -or $mhz -le 0) { return }
            $hz = [long]($mhz * 1000000)
            $mode = switch ($modeBox.SelectedIndex) { 1 { "AM" } 2 { "NFM" } default { "FM" } }
            $gain = "$([int]$gainSlider.Value)"
            $err = Start-RadioTuner -FrequencyHz $hz -Mode $mode -Gain $gain
            if ([string]::IsNullOrWhiteSpace($err)) {
                $status.Text = "PLAYING $mhz MHz [$mode] @ ${gain}dB."
            } else {
                $status.Text = "Error: $err"
            }
        }
    }.GetNewClosure())

    $stopBtn.Add_Click({
        Invoke-AppAction -Context "Stop radio" -Action {
            Stop-RadioTuner
            $status.Text = "Stopped."
        }
    }.GetNewClosure())

    # Always stop audio and release the dongle when the tuner window closes.
    $win.Add_Closed({
        Invoke-AppAction -Context "Close radio tuner" -Action { Stop-RadioTuner }
    }.GetNewClosure())

    $win.Content = $stack
    Apply-SnifferOpsFont -Root $win
    Apply-SnifferOpsSpecialFonts -Root $win
    [void]$win.ShowDialog()
}
# ---------------------------------------------------------------------------

# Entry point when a signal is tapped: query lenses and route accordingly.
function Invoke-SignalLens {
    param([object] $Signal)

    Invoke-AppAction -Context "Open signal lens" -Action {
        if (-not $Signal -or -not $Signal.FrequencyHz) {
            Add-LogLine "Select an SDR frequency row first."
            return
        }

        $matches = Get-MatchingLenses -Signal $Signal
        if ($matches.Count -eq 0) {
            Add-LogLine "No decoder available for $($Signal.Label) ($($Signal.Frequency))."
            [System.Windows.MessageBox]::Show(
                "No decoder available for this signal type.",
                "SnifferOps", [System.Windows.MessageBoxButton]::OK,
                [System.Windows.MessageBoxImage]::Information) | Out-Null
            return
        }

        if ($matches.Count -eq 1) {
            Invoke-LensDirective -Lens $matches[0] -Signal $Signal
            return
        }

        Show-LensChooserWindow -Signal $Signal -Matches $matches
    }
}

# Executes the directive a lens returns from Activate().
function Invoke-LensDirective {
    param(
        [object] $Lens,
        [object] $Signal
    )

    $directive = $Lens.Activate($Signal)
    switch ($directive.Kind) {
        "listen" {
            Start-LensListen -Signal $Signal -Mode $directive.Mode `
                -AllowModeOverride ([bool] $directive.AllowModeOverride) -Title $directive.Title
        }
        "adsb" {
            Start-AdsbCapture
        }
        "notimplemented" {
            Add-LogLine "$($Lens.GetDisplayName()): $($directive.Message)"
            [System.Windows.MessageBox]::Show(
                $directive.Message,
                "SnifferOps - $($Lens.GetDisplayName())",
                [System.Windows.MessageBoxButton]::OK,
                [System.Windows.MessageBoxImage]::Information) | Out-Null
        }
        default {
            Add-LogLine "Lens $($Lens.Name) returned unknown directive '$($directive.Kind)'."
        }
    }
}

# Chooser shown when more than one lens matches (e.g. voice + data overlap).
function Show-LensChooserWindow {
    param(
        [object] $Signal,
        [object[]] $Matches
    )

    $chooser = New-Object System.Windows.Window
    Set-SnifferOpsWindowIcon -TargetWindow $chooser
    $chooser.Title = "SnifferOps - Choose viewer"
    $chooser.Width = 420
    $chooser.SizeToContent = "Height"
    $chooser.ResizeMode = "NoResize"
    $chooser.Background = $script:BrushConverter.ConvertFromString("#020617")
    $chooser.WindowStartupLocation = "CenterOwner"
    $chooser.Owner = $Window

    $stack = New-Object System.Windows.Controls.StackPanel
    $stack.Margin = "18"

    $title = New-Object System.Windows.Controls.TextBlock
    $title.Text = "MULTIPLE VIEWERS"
    $title.Foreground = $script:BrushConverter.ConvertFromString("#8B5CF6")
    $title.FontFamily = "Consolas"
    $title.FontSize = 20
    $title.FontWeight = "Bold"
    $title.Margin = "0,0,0,8"
    [void]$stack.Children.Add($title)

    $info = New-Object System.Windows.Controls.TextBlock
    $info.Text = "$($Signal.Frequency)  |  $($Signal.Label)"
    $info.Foreground = $script:BrushConverter.ConvertFromString("#E5E7EB")
    $info.FontFamily = "Consolas"
    $info.FontSize = 13
    $info.TextWrapping = "Wrap"
    $info.Margin = "0,0,0,14"
    [void]$stack.Children.Add($info)

    foreach ($lens in $Matches) {
        $captured = $lens
        $btn = New-Object System.Windows.Controls.Button
        $suffix = if ($captured.Implemented) { "" } else { "  (not built)" }
        $btn.Content = "$($captured.GetDisplayName())$suffix"
        $btn.Height = 42
        $btn.Margin = "0,0,0,8"
        $btn.BorderThickness = 0
        $btn.FontFamily = "Consolas"
        $btn.FontWeight = "Bold"
        $btn.Foreground = $script:BrushConverter.ConvertFromString("White")
        $btn.Background = $script:BrushConverter.ConvertFromString($(if ($captured.Kind -eq "voice") { "#8B5CF6" } else { "#2563EB" }))
        $btn.Add_Click({
            Invoke-LensDirective -Lens $captured -Signal $Signal
            $chooser.Close()
        }.GetNewClosure())
        [void]$stack.Children.Add($btn)
    }

    $chooser.Content = $stack
    Apply-SnifferOpsFont -Root $chooser
    Apply-SnifferOpsSpecialFonts -Root $chooser
    [void]$chooser.ShowDialog()
}

# Maps a lens directive mode token (wbfm/am/nfm/fm) to a tuner mode token.
function ConvertTo-TunerMode {
    param([string] $Mode)
    switch ($Mode) {
        "am"   { "AM" }
        "wbfm" { "FM" }
        "nfm"  { "NFM" }
        "fm"   { "NFM" }
        default { "FM" }
    }
}

# Starts rtl_fm at the given frequency/mode and plays its PCM through winmm.
# This is the same proven chain the FM/AM tuner uses. Returns any error string.
function Start-LensAudio {
    param([long] $FrequencyHz, [string] $Mode)
    $cfg = Get-TunerConfig -FrequencyHz $FrequencyHz -Mode (ConvertTo-TunerMode $Mode) -Gain $script:DefaultTunerGain
    $script:AudioStreamer = New-Object PcmWaveStreamer
    $script:AudioStreamer.Start($RtlFmPath, $cfg.Args, $ToolRoot, $cfg.SampleRate)
    Start-Sleep -Milliseconds 500
    return $script:AudioStreamer.ErrorText
}

# Demodulates a signal to audio with rtl_fm and opens the listening window.
# rtl_fm needs the dongle exclusively, so rtl_tcp is paused for the duration and
# restored by Stop-SdrAudio when listening ends.
function Start-LensListen {
    param(
        [object] $Signal,
        [string] $Mode,
        [bool] $AllowModeOverride,
        [string] $Title
    )

    Invoke-AppAction -Context "Start SDR audio" -Action {
        if (-not $Signal -or -not $Signal.FrequencyHz) {
            Add-LogLine "Select an SDR frequency row first."
            return
        }
        if (-not (Test-Path $RtlFmPath)) {
            Add-LogLine "Missing rtl_fm.exe in $ToolRoot."
            return
        }

        $frequency = [long]$Signal.FrequencyHz

        Stop-SdrAudio -RestoreServer:$false

        if (Get-Process rtl_tcp -ErrorAction SilentlyContinue) {
            Add-LogLine "Pausing rtl_tcp so the dongle can demodulate audio..."
            Get-Process rtl_tcp -ErrorAction SilentlyContinue | Stop-Process -Force
            Start-Sleep -Milliseconds 400
            $script:RestartRtlTcpAfterListen = $true
        }

        $startupError = Start-LensAudio -FrequencyHz $frequency -Mode $Mode
        if (-not [string]::IsNullOrWhiteSpace($startupError)) {
            throw $startupError
        }

        Add-LogLine "Listening to $(Format-Frequency -Frequency $frequency) via rtl_fm as ${Mode}: $($Signal.Label)"
        Show-ListenerWindow -Signal $Signal -Mode $Mode -AllowModeOverride $AllowModeOverride -Title $Title
    }
}

# Restarts the demodulator at the same frequency with a new mode (manual override).
function Set-ListenMode {
    param(
        [object] $Signal,
        [string] $Mode
    )

    Invoke-AppAction -Context "Change listen mode" -Action {
        Stop-SdrAudio -RestoreServer:$false
        $startupError = Start-LensAudio -FrequencyHz ([long]$Signal.FrequencyHz) -Mode $Mode
        if (-not [string]::IsNullOrWhiteSpace($startupError)) {
            Add-LogLine "rtl_fm error switching mode: $startupError"
            return
        }
        Add-LogLine "Switched $($Signal.Label) to ${Mode}."
    }
}

function Show-ListenerWindow {
    param(
        [object] $Signal,
        [string] $Mode,
        [bool] $AllowModeOverride = $false,
        [string] $Title = "LISTENING"
    )

    $listenWindow = New-Object System.Windows.Window
    Set-SnifferOpsWindowIcon -TargetWindow $listenWindow
    $listenWindow.Title = "SnifferOps - Listening"
    $listenWindow.Width = 420
    $listenWindow.SizeToContent = "Height"
    $listenWindow.ResizeMode = "NoResize"
    $listenWindow.Background = $script:BrushConverter.ConvertFromString("#020617")
    $listenWindow.WindowStartupLocation = "CenterOwner"
    $listenWindow.Owner = $Window

    $stack = New-Object System.Windows.Controls.StackPanel
    $stack.Margin = "18"

    $titleBlock = New-Object System.Windows.Controls.TextBlock
    $titleBlock.Text = "LISTENING"
    $titleBlock.Foreground = $script:BrushConverter.ConvertFromString("#8B5CF6")
    $titleBlock.FontFamily = "Consolas"
    $titleBlock.FontSize = 22
    $titleBlock.FontWeight = "Bold"
    $titleBlock.Margin = "0,0,0,6"
    [void]$stack.Children.Add($titleBlock)

    if ($Title) {
        $lensLabel = New-Object System.Windows.Controls.TextBlock
        $lensLabel.Text = $Title
        $lensLabel.Foreground = $script:BrushConverter.ConvertFromString("#C4B5FD")
        $lensLabel.FontFamily = "Consolas"
        $lensLabel.FontSize = 12
        $lensLabel.Margin = "0,0,0,10"
        [void]$stack.Children.Add($lensLabel)
    }

    $info = New-Object System.Windows.Controls.TextBlock
    $info.Text = "$($Signal.Frequency)  |  $($Signal.Label)  |  $($Mode.ToUpperInvariant())"
    $info.Foreground = $script:BrushConverter.ConvertFromString("#E5E7EB")
    $info.FontFamily = "Consolas"
    $info.FontSize = 13
    $info.TextWrapping = "Wrap"
    $info.Margin = "0,0,0,8"
    [void]$stack.Children.Add($info)

    $hint = New-Object System.Windows.Controls.TextBlock
    $hint.Text = "Audio is demodulated directly by rtl_fm (rtl_tcp is paused while listening). $($Signal.Audio)"
    $hint.Foreground = $script:BrushConverter.ConvertFromString("#9CA3AF")
    $hint.FontSize = 12
    $hint.TextWrapping = "Wrap"
    $hint.Margin = "0,0,0,14"
    [void]$stack.Children.Add($hint)

    if ($AllowModeOverride) {
        $modeLabel = New-Object System.Windows.Controls.TextBlock
        $modeLabel.Text = "MODE"
        $modeLabel.Foreground = $script:BrushConverter.ConvertFromString("#9CA3AF")
        $modeLabel.FontFamily = "Consolas"
        $modeLabel.FontSize = 11
        $modeLabel.Margin = "0,0,0,4"
        [void]$stack.Children.Add($modeLabel)

        $combo = New-Object System.Windows.Controls.ComboBox
        $combo.FontFamily = "Consolas"
        $combo.Margin = "0,0,0,14"
        foreach ($m in "NFM", "WFM", "AM") { [void]$combo.Items.Add($m) }
        $combo.SelectedItem = switch ($Mode) { "am" { "AM" } "wbfm" { "WFM" } default { "NFM" } }
        $combo.Add_SelectionChanged({
            $sel = "$($combo.SelectedItem)"
            $newMode = switch ($sel) { "AM" { "am" } "WFM" { "wbfm" } default { "nfm" } }
            Set-ListenMode -Signal $Signal -Mode $newMode
            $info.Text = "$($Signal.Frequency)  |  $($Signal.Label)  |  $sel"
        }.GetNewClosure())
        [void]$stack.Children.Add($combo)
    }

    $stop = New-Object System.Windows.Controls.Button
    $stop.Content = "STOP LISTENING"
    $stop.Height = 44
    $stop.Background = $script:BrushConverter.ConvertFromString("#EF4444")
    $stop.Foreground = $script:BrushConverter.ConvertFromString("White")
    $stop.BorderThickness = 0
    $stop.FontFamily = "Consolas"
    $stop.FontWeight = "Bold"
    $stop.Add_Click({
        Stop-SdrAudio
        $listenWindow.Close()
    })
    [void]$stack.Children.Add($stop)

    $listenWindow.Add_Closed({
        Stop-SdrAudio
        Refresh-ScannerCounts
    })

    $listenWindow.Content = $stack
    Apply-SnifferOpsFont -Root $listenWindow
    Apply-SnifferOpsSpecialFonts -Root $listenWindow
    [void]$listenWindow.ShowDialog()
}

function Show-DetailWindow {
    param(
        [string] $Title,
        [string] $Accent,
        [object[]] $Items
    )

    if (-not $Items -or $Items.Count -eq 0) {
        $Items = @([pscustomobject][ordered]@{
            Name = "No items detected"
            Address = ""
            Status = ""
            Type = $Title
            Notes = "Refresh and try again."
        })
    }

    $detailWindow = New-Object System.Windows.Window
    Set-SnifferOpsWindowIcon -TargetWindow $detailWindow
    $detailWindow.Title = "SnifferOps - $Title"
    $detailWindow.Width = 1180
    $detailWindow.Height = 620
    $detailWindow.MinWidth = 760
    $detailWindow.MinHeight = 420
    $detailWindow.Background = $script:BrushConverter.ConvertFromString("#020617")
    $detailWindow.WindowStartupLocation = "CenterOwner"
    $detailWindow.Owner = $Window

    $root = New-Object System.Windows.Controls.DockPanel
    $root.Margin = "16"

    $header = New-Object System.Windows.Controls.TextBlock
    $header.Text = $Title.ToUpperInvariant()
    $header.Foreground = $script:BrushConverter.ConvertFromString($Accent)
    $header.FontFamily = "Consolas"
    $header.FontSize = 22
    $header.FontWeight = "Bold"
    $header.Margin = "0,0,0,12"
    [System.Windows.Controls.DockPanel]::SetDock($header, "Top")
    [void]$root.Children.Add($header)

    $estimateFooter = New-Object System.Windows.Controls.TextBlock
    $estimateFooter.Text = "* type/info is estimated"
    $estimateFooter.Foreground = $script:BrushConverter.ConvertFromString("#9CA3AF")
    $estimateFooter.FontFamily = "Consolas"
    $estimateFooter.FontSize = 12
    $estimateFooter.Margin = "0,10,0,0"
    [System.Windows.Controls.DockPanel]::SetDock($estimateFooter, "Bottom")
    [void]$root.Children.Add($estimateFooter)

    if ($Title -eq "SDR Radio") {
        $listenPanel = New-Object System.Windows.Controls.StackPanel
        $listenPanel.Orientation = "Horizontal"
        $listenPanel.Margin = "0,0,0,12"
        [System.Windows.Controls.DockPanel]::SetDock($listenPanel, "Top")

        $listenButton = New-Object System.Windows.Controls.Button
        $listenButton.Content = "OPEN SELECTED"
        $listenButton.Width = 160
        $listenButton.Height = 36
        $listenButton.Background = $script:BrushConverter.ConvertFromString("#8B5CF6")
        $listenButton.Foreground = $script:BrushConverter.ConvertFromString("White")
        $listenButton.BorderThickness = 0
        $listenButton.FontFamily = "Consolas"
        $listenButton.FontWeight = "Bold"
        [void]$listenPanel.Children.Add($listenButton)

        $deepScanButton = New-Object System.Windows.Controls.Button
        $deepScanButton.Content = "DEEP SCAN (rtl_power)"
        $deepScanButton.Width = 190
        $deepScanButton.Height = 36
        $deepScanButton.Margin = "8,0,0,0"
        $deepScanButton.Background = $script:BrushConverter.ConvertFromString("#2563EB")
        $deepScanButton.Foreground = $script:BrushConverter.ConvertFromString("White")
        $deepScanButton.BorderThickness = 0
        $deepScanButton.FontFamily = "Consolas"
        $deepScanButton.FontWeight = "Bold"
        [void]$listenPanel.Children.Add($deepScanButton)

        $listenHint = New-Object System.Windows.Controls.TextBlock
        $listenHint.Text = "  Select a row and use OPEN SELECTED to listen/decode. Double-click a row for details."
        $listenHint.Foreground = $script:BrushConverter.ConvertFromString("#9CA3AF")
        $listenHint.FontFamily = "Consolas"
        $listenHint.FontSize = 12
        $listenHint.VerticalAlignment = "Center"
        [void]$listenPanel.Children.Add($listenHint)

        [void]$root.Children.Add($listenPanel)
    }

    $grid = New-Object System.Windows.Controls.DataGrid
    $grid.AutoGenerateColumns = $true
    $grid.IsReadOnly = $true
    $grid.CanUserAddRows = $false
    $grid.CanUserDeleteRows = $false
    $grid.GridLinesVisibility = "Horizontal"
    $grid.Background = $script:BrushConverter.ConvertFromString("#0B1120")
    $grid.Foreground = $script:BrushConverter.ConvertFromString("#E5E7EB")
    $grid.RowBackground = $script:BrushConverter.ConvertFromString("#111827")
    $grid.AlternatingRowBackground = $script:BrushConverter.ConvertFromString("#0F172A")
    $grid.BorderBrush = $script:BrushConverter.ConvertFromString("#374151")
    $grid.FontFamily = "Consolas"
    $grid.FontSize = 12
    $grid.HorizontalAlignment = "Stretch"
    $grid.VerticalAlignment = "Stretch"
    $grid.HorizontalScrollBarVisibility = "Auto"

    $compactColumns = @(Get-CompactDetailColumns -Title $Title)
    $visibleNames = @($compactColumns | ForEach-Object { $_.Name })
    $headers = @{}
    foreach ($column in $compactColumns) { $headers[$column.Name] = $column.Header }
    $grid.Add_AutoGeneratingColumn({
        param($eventSender, $eventArgs)
        if ($visibleNames -notcontains $eventArgs.PropertyName) {
            $eventArgs.Cancel = $true
            return
        }
        $eventArgs.Column.Header = $headers[$eventArgs.PropertyName]
        if ($eventArgs.Column -is [System.Windows.Controls.DataGridTextColumn]) {
            $eventArgs.Column.ElementStyle = New-DataGridTextStyle
        }
        switch ($eventArgs.PropertyName) {
            "Name" { $eventArgs.Column.Width = New-Object System.Windows.Controls.DataGridLength(1.4, [System.Windows.Controls.DataGridLengthUnitType]::Star); break }
            "Signal" { $eventArgs.Column.Width = New-Object System.Windows.Controls.DataGridLength(1.4, [System.Windows.Controls.DataGridLengthUnitType]::Star); break }
            "SpecificType" { $eventArgs.Column.Width = New-Object System.Windows.Controls.DataGridLength(1.5, [System.Windows.Controls.DataGridLengthUnitType]::Star); break }
            "Type" { $eventArgs.Column.Width = New-Object System.Windows.Controls.DataGridLength(1.2, [System.Windows.Controls.DataGridLengthUnitType]::Star); break }
            "Label" { $eventArgs.Column.Width = New-Object System.Windows.Controls.DataGridLength(1.8, [System.Windows.Controls.DataGridLengthUnitType]::Star); break }
            "Address" { $eventArgs.Column.Width = New-Object System.Windows.Controls.DataGridLength(1.3, [System.Windows.Controls.DataGridLengthUnitType]::Star); break }
            "Security" { $eventArgs.Column.Width = New-Object System.Windows.Controls.DataGridLength(1.5, [System.Windows.Controls.DataGridLengthUnitType]::Star); break }
            "Decoder" { $eventArgs.Column.Width = New-Object System.Windows.Controls.DataGridLength(1.4, [System.Windows.Controls.DataGridLengthUnitType]::Star); break }
            "Notes" { $eventArgs.Column.Width = New-Object System.Windows.Controls.DataGridLength(1.4, [System.Windows.Controls.DataGridLengthUnitType]::Star); break }
            "Evidence" { $eventArgs.Column.Width = New-Object System.Windows.Controls.DataGridLength(1.7, [System.Windows.Controls.DataGridLengthUnitType]::Star); break }
            "LastEvent" { $eventArgs.Column.Width = New-Object System.Windows.Controls.DataGridLength(2.0, [System.Windows.Controls.DataGridLengthUnitType]::Star); break }
            "Level" { $eventArgs.Column.Width = New-Object System.Windows.Controls.DataGridLength(85); break }
            "Class" { $eventArgs.Column.Width = New-Object System.Windows.Controls.DataGridLength(90); break }
            "Strength" { $eventArgs.Column.Width = New-Object System.Windows.Controls.DataGridLength(80); break }
            "Status" { $eventArgs.Column.Width = New-Object System.Windows.Controls.DataGridLength(95); break }
            "Seen" { $eventArgs.Column.Width = New-Object System.Windows.Controls.DataGridLength(65); break }
            "Nodes" { $eventArgs.Column.Width = New-Object System.Windows.Controls.DataGridLength(65); break }
            "PowerDb" { $eventArgs.Column.Width = New-Object System.Windows.Controls.DataGridLength(85); break }
            "Channel" { $eventArgs.Column.Width = New-Object System.Windows.Controls.DataGridLength(75); break }
            "Modulation" { $eventArgs.Column.Width = New-Object System.Windows.Controls.DataGridLength(110); break }
            "Source" { $eventArgs.Column.Width = New-Object System.Windows.Controls.DataGridLength(90); break }
            default { $eventArgs.Column.Width = New-Object System.Windows.Controls.DataGridLength(1, [System.Windows.Controls.DataGridLengthUnitType]::Star); break }
        }
    }.GetNewClosure())
    $grid.ItemsSource = $Items

    $detailAction = {
        if ($grid.SelectedItem) {
            if ($Title -eq "Awareness Locations" -and $grid.SelectedItem.LocationKey) {
                $detailWindow.Close()
                Show-AwarenessTimelineWindow -LocationKey ([string]$grid.SelectedItem.LocationKey)
                return
            }
            Show-SignalDetailWindow -Title $Title -Accent $Accent -Item $grid.SelectedItem
        }
    }.GetNewClosure()
    $grid.Add_MouseDoubleClick($detailAction)

    if ($Title -eq "SDR Radio") {
        $listenAction = {
            if ($grid.SelectedItem) {
                Invoke-SignalLens -Signal $grid.SelectedItem
            } else {
                Add-LogLine "Select an SDR row first."
            }
        }
        $listenButton.Add_Click($listenAction)

        $deepScanButton.Add_Click({
            Invoke-AppAction -Context "Deep spectrum scan" -Action {
                $deepScanButton.IsEnabled = $false
                try {
                    $hits = @(Invoke-SdrPowerScan)
                    if ($hits.Count -gt 0) {
                        $grid.ItemsSource = $hits
                    } else {
                        Add-LogLine "Deep scan found no peaks above the noise floor."
                    }
                    Refresh-ScannerCounts
                } finally {
                    $deepScanButton.IsEnabled = $true
                }
            }
        }.GetNewClosure())
    }

    [void]$root.Children.Add($grid)

    $detailWindow.Content = $root
    Apply-SnifferOpsFont -Root $detailWindow
    Apply-SnifferOpsSpecialFonts -Root $detailWindow
    [void]$detailWindow.ShowDialog()
}

function Get-RtlStatusText {
    if (-not (Test-Path $RtlTcpPath)) {
        return "RTL-SDR tools not installed in tools\rtl-sdr-blog"
    }

    $running = Get-Process rtl_tcp -ErrorAction SilentlyContinue
    if ($running) {
        return "RTL-SDR SERVER LIVE"
    }

    return "RTL-SDR READY"
}

function Add-LogLine {
    param([string] $Message)
    $timestamp = Get-Date -Format "HH:mm:ss"
    $current = $LogBox.Text
    $next = "[$timestamp] $Message"
    if ([string]::IsNullOrWhiteSpace($current)) {
        $LogBox.Text = $next
    } else {
        $LogBox.Text = "$current`r`n$next"
    }
    $LogBox.ScrollToEnd()
}

function Set-UiStatus {
    param(
        [string] $State,
        [string] $Message,
        [bool] $Active
    )

    $LiveText.Text = $State
    $SdrStatusText.Text = $Message
    $ConnectButton.Content = if ($Active) { "STOP LOCAL RTL_TCP" } else { "START LOCAL RTL_TCP" }
    if ($Window -and $Window.Resources) {
        $ConnectButton.Background = if ($Active) { $Window.Resources["ButtonRedBrush"] } else { $Window.Resources["ButtonBlueBrush"] }
    } else {
        $ConnectButton.Background = $script:BrushConverter.ConvertFromString($(if ($Active) { "#EF4444" } else { "#0EA5E9" }))
    }
    $ConnectButton.Foreground = $script:BrushConverter.ConvertFromString("White")
    $script:ScanActive = $Active
}

function Refresh-ScannerCounts {
    [void](Sync-LocalAwarenessSnapshot)
    $wifi = Get-WifiCount
    $bt = Get-BluetoothCount
    $running = Get-Process rtl_tcp -ErrorAction SilentlyContinue
    $sdr = @($script:SdrSignals | Where-Object { $_.Source -eq "rtl_power" }).Count
    $alertRows = @(Get-AlertDetails | Where-Object { $_.Level -ne "CLEAR" })
    $alertCountValue = $alertRows.Count

    $WifiCount.Text = [string]$wifi
    $BluetoothCount.Text = [string]$bt
    $CellCount.Text = "0"
    $SdrCount.Text = [string]$sdr
    $AlertCount.Text = [string]$alertCountValue

    $WifiTileCount.Text = [string]$wifi
    $BluetoothTileCount.Text = [string]$bt
    $NfcTileCount.Text = "0"
    $CellTileCount.Text = "0"
    $SdrTileCount.Text = [string]$sdr
    $AlertTileCount.Text = [string]$alertCountValue

    $LocalIpText.Text = "$(Get-LanIpAddress):$Port"
    $EndpointText.Text = "SDR $(Get-LanIpAddress):$Port  |  SYNC $(Get-LanIpAddress):$AwarenessSyncPort"
    if ($MainSignalGrid) {
        $MainSignalGrid.ItemsSource = @(Get-MainSignalRows)
    }
    Update-AwarenessMapPanel

    if ($running) {
        $hitText = if ($sdr -gt 0) { " - $sdr measured RF peak(s)" } else { " - no measured peaks yet" }
        Set-UiStatus "LIVE" "Network SDR: rtl_tcp on $(Get-LanIpAddress):$Port$hitText" $true
    } else {
        Set-UiStatus "IDLE" (Get-RtlStatusText) $false
    }
}

function Start-RtlTcpServer {
    if (-not (Test-Path $RtlTcpPath)) {
        Add-LogLine "Missing rtl_tcp.exe. Run scripts\install-rtl-sdr-blog-tools.ps1 first."
        Set-UiStatus "IDLE" "RTL-SDR tools not installed" $false
        return
    }

    Get-Process rtl_tcp -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Milliseconds 500

    if (Test-Path $OutLog) { Remove-Item -LiteralPath $OutLog -Force }
    if (Test-Path $ErrLog) { Remove-Item -LiteralPath $ErrLog -Force }

    $args = "-a $BindAddress -p $Port"
    $script:RtlTcpProcess = Start-Process -FilePath $RtlTcpPath `
        -ArgumentList $args `
        -WorkingDirectory $ToolRoot `
        -RedirectStandardOutput $OutLog `
        -RedirectStandardError $ErrLog `
        -WindowStyle Hidden `
        -PassThru

    $script:StartTime = Get-Date
    Start-Sleep -Milliseconds 700

    if ($script:RtlTcpProcess.HasExited) {
        $errorText = if (Test-Path $ErrLog) { Get-Content $ErrLog -Raw } else { "rtl_tcp exited immediately" }
        Add-LogLine $errorText.Trim()
        Set-UiStatus "IDLE" "RTL-SDR failed to start" $false
        return
    }

    Set-UiStatus "LIVE" "Network SDR: rtl_tcp on $(Get-LanIpAddress):$Port" $true
    Add-LogLine "Started rtl_tcp on ${BindAddress}:$Port"
    Add-LogLine "Use $(Get-LanIpAddress) and port $Port from the phone app, or leave this Windows app running standalone."
    Refresh-ScannerCounts
}

function Start-RemoteRtlServerFromScript {
    if (-not (Test-Path $StartRtlTcpScript)) {
        Add-LogLine "Missing start script: $StartRtlTcpScript"
        return
    }

    $argumentList = "-ExecutionPolicy Bypass -File `"$StartRtlTcpScript`""
    Start-Process -FilePath "powershell.exe" `
        -ArgumentList $argumentList `
        -WorkingDirectory $RepoRoot `
        -WindowStyle Normal | Out-Null

    Add-LogLine "Started Windows RTL server script for mobile app data."
    Add-LogLine "Command: powershell -ExecutionPolicy Bypass -File `"$StartRtlTcpScript`""
    Start-Sleep -Milliseconds 500
    Refresh-ScannerCounts
}

function Stop-RtlTcpServer {
    Get-Process rtl_tcp -ErrorAction SilentlyContinue | Stop-Process -Force
    $script:RtlTcpProcess = $null
    $script:StartTime = $null
    Set-UiStatus "IDLE" "RTL-SDR READY" $false
    Add-LogLine "Stopped rtl_tcp."
    Refresh-ScannerCounts
}

# Capture live ADS-B for a fixed window with rtl_adsb.exe, decode frames, and
# hand the aircraft list to the map backend. rtl_adsb needs exclusive access to
# the dongle, so rtl_tcp is stopped for the duration and restarted afterward.
function Start-AdsbCapture {
    if (-not (Test-Path $RtlAdsbPath)) {
        Add-LogLine "Missing rtl_adsb.exe in $ToolRoot."
        [System.Windows.MessageBox]::Show(
            "rtl_adsb.exe was not found. Install the RTL-SDR tools first.",
            "SnifferOps - ADS-B", [System.Windows.MessageBoxButton]::OK,
            [System.Windows.MessageBoxImage]::Warning) | Out-Null
        return
    }

    $seconds = [int]$script:AdsbCaptureSeconds
    $chunkSeconds = [math]::Max(5, [int]$script:AdsbCaptureChunkSeconds)
    $adsbOut = Join-Path $RepoRoot "rtl_adsb.out.log"
    $adsbErr = Join-Path $RepoRoot "rtl_adsb.err.log"

    $serverWasRunning = [bool](Get-Process rtl_tcp -ErrorAction SilentlyContinue)
    if ($serverWasRunning) {
        Add-LogLine "Pausing rtl_tcp to free the dongle for ADS-B capture..."
        Get-Process rtl_tcp -ErrorAction SilentlyContinue | Stop-Process -Force
        Start-Sleep -Milliseconds 500
    }

    if (Test-Path $adsbOut) { Remove-Item -LiteralPath $adsbOut -Force }
    if (Test-Path $adsbErr) { Remove-Item -LiteralPath $adsbErr -Force }

    Add-LogLine "Capturing ADS-B on 1090 MHz for up to ${seconds}s (rtl_adsb)..."
    $frames = @()
    $validFrameCount = 0
    $aircraft = @()
    $positioned = @()
    $elapsed = 0

    while ($elapsed -lt $seconds) {
        $runSeconds = [math]::Min($chunkSeconds, $seconds - $elapsed)
        $chunkOut = Join-Path $RepoRoot ("rtl_adsb.chunk.{0}.out.log" -f $elapsed)
        $chunkErr = Join-Path $RepoRoot ("rtl_adsb.chunk.{0}.err.log" -f $elapsed)
        if (Test-Path $chunkOut) { Remove-Item -LiteralPath $chunkOut -Force }
        if (Test-Path $chunkErr) { Remove-Item -LiteralPath $chunkErr -Force }

        $proc = Start-Process -FilePath $RtlAdsbPath `
            -WorkingDirectory $ToolRoot `
            -RedirectStandardOutput $chunkOut `
            -RedirectStandardError $chunkErr `
            -WindowStyle Hidden `
            -PassThru

        try {
            $deadline = (Get-Date).AddSeconds($runSeconds)
            while ((Get-Date) -lt $deadline -and -not $proc.HasExited) {
                Start-Sleep -Milliseconds 500
            }
        } finally {
            if (-not $proc.HasExited) {
                try { $proc.Kill() } catch {}
            }
        }
        Start-Sleep -Milliseconds 300

        if (Test-Path $chunkOut) {
            $chunkFrames = @(Get-Content -Path $chunkOut -ErrorAction SilentlyContinue |
                Where-Object { $_ -match '\*[0-9A-Fa-f]+;' })
            if ($chunkFrames.Count -gt 0) {
                Add-Content -Path $adsbOut -Value $chunkFrames -ErrorAction SilentlyContinue
                $frames += $chunkFrames
            }
        }
        if (Test-Path $chunkErr) {
            Add-Content -Path $adsbErr -Value (Get-Content -Path $chunkErr -ErrorAction SilentlyContinue) -ErrorAction SilentlyContinue
        }
        Remove-Item -LiteralPath $chunkOut,$chunkErr -Force -ErrorAction SilentlyContinue

        $validFrameCount = @($frames | Where-Object {
            $bytes = Convert-HexToBytes $_
            $bytes.Length -eq 14 -and ((Get-AdsbDownlinkFormat -Bytes $bytes) -in 17, 18) -and (Test-AdsbChecksum -Bytes $bytes)
        }).Count
        $aircraft = @(Convert-AdsbFrames -Frames $frames)
        $positioned = @($aircraft | Where-Object { $null -ne $_.Lat })
        $elapsed += $runSeconds

        Add-LogLine "ADS-B chunk ${elapsed}s: $($frames.Count) raw, $validFrameCount verified, $($positioned.Count) positioned."
        if ($positioned.Count -gt 0) { break }
    }
    Add-LogLine "ADS-B capture done: $($frames.Count) raw frame(s), $validFrameCount verified ADS-B frame(s)."

    if ($serverWasRunning) {
        Start-RtlTcpServer
    }

    Add-LogLine "Decoded $($aircraft.Count) aircraft ($($positioned.Count) with position)."

    if ($aircraft.Count -eq 0) {
        [System.Windows.MessageBox]::Show(
            "No verified ADS-B aircraft were decoded in ${elapsed}s.`n`nThis can happen indoors, with a weak 1090 MHz antenna, or when rtl_adsb only sees noise. Try near a window or with a better antenna.",
            "SnifferOps - ADS-B", [System.Windows.MessageBoxButton]::OK,
            [System.Windows.MessageBoxImage]::Information) | Out-Null
        return
    }

    $target = Invoke-AdsbMapBackend -Aircraft $aircraft -OutputDir $RepoRoot
    Add-LogLine "ADS-B map output: $target"
}

function Test-RtlSdrDongle {
    if (-not (Test-Path $RtlTestPath)) {
        Add-LogLine "Missing rtl_test.exe. Run scripts\install-rtl-sdr-blog-tools.ps1 first."
        return
    }

    Add-LogLine "Running rtl_test -t..."
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $RtlTestPath
    $psi.Arguments = "-t"
    $psi.WorkingDirectory = $ToolRoot
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $proc = [System.Diagnostics.Process]::Start($psi)
    $stdout = $proc.StandardOutput.ReadToEnd()
    $stderr = $proc.StandardError.ReadToEnd()
    $proc.WaitForExit()

    $result = (($stdout, $stderr) -join "`r`n").Trim()
    if ([string]::IsNullOrWhiteSpace($result)) {
        $result = "rtl_test finished with exit code $($proc.ExitCode)."
    }
    Add-LogLine $result
}

[xml] $xaml = @"
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="SnifferOps Windows" Height="860" Width="1280"
        MinHeight="760" MinWidth="980" Background="#020617"
        WindowStartupLocation="CenterScreen">
    <Window.Resources>
        <LinearGradientBrush x:Key="PanelBrush" StartPoint="0,0" EndPoint="1,1">
            <GradientStop Color="#111827" Offset="0"/>
            <GradientStop Color="#07111E" Offset="1"/>
        </LinearGradientBrush>
        <LinearGradientBrush x:Key="ButtonBlueBrush" StartPoint="0,0" EndPoint="1,1">
            <GradientStop Color="#0EA5E9" Offset="0"/>
            <GradientStop Color="#0B4FA4" Offset="1"/>
        </LinearGradientBrush>
        <LinearGradientBrush x:Key="ButtonRedBrush" StartPoint="0,0" EndPoint="1,1">
            <GradientStop Color="#EF4444" Offset="0"/>
            <GradientStop Color="#7F0000" Offset="1"/>
        </LinearGradientBrush>
        <LinearGradientBrush x:Key="ButtonGreenBrush" StartPoint="0,0" EndPoint="1,1">
            <GradientStop Color="#10B981" Offset="0"/>
            <GradientStop Color="#046C4E" Offset="1"/>
        </LinearGradientBrush>
    </Window.Resources>
    <ScrollViewer VerticalScrollBarVisibility="Auto">
        <Grid>
            <Grid.Background>
                <DrawingBrush TileMode="Tile" Viewport="0,0,28,28" ViewportUnits="Absolute">
                    <DrawingBrush.Drawing>
                        <GeometryDrawing Brush="#020617">
                            <GeometryDrawing.Pen>
                                <Pen Brush="#0B3A35" Thickness="0.45"/>
                            </GeometryDrawing.Pen>
                            <GeometryDrawing.Geometry>
                                <GeometryGroup>
                                    <LineGeometry StartPoint="0,0" EndPoint="28,0"/>
                                    <LineGeometry StartPoint="0,0" EndPoint="0,28"/>
                                </GeometryGroup>
                            </GeometryDrawing.Geometry>
                        </GeometryDrawing>
                    </DrawingBrush.Drawing>
                </DrawingBrush>
            </Grid.Background>
            <Border Margin="8" BorderBrush="#0B6B57" BorderThickness="1" CornerRadius="7" Padding="22" Background="#D9020610">
            <StackPanel>
                <DockPanel LastChildFill="False" Margin="0,0,0,8">
                    <StackPanel DockPanel.Dock="Left" Orientation="Horizontal">
                        <Image x:Name="HeaderIconImage" Width="58" Height="58" Margin="0,0,12,0"/>
                        <StackPanel VerticalAlignment="Center">
                            <TextBlock Tag="GradientTitle" Text="SNIFFER OPS" Foreground="#21F982"
                                       FontFamily="Consolas" FontSize="28" FontWeight="Bold"/>
                            <TextBlock Text="WINDOWS COMPANION" Foreground="#637082"
                                       FontFamily="Consolas" FontSize="14" Margin="1,-2,0,0"/>
                        </StackPanel>
                    </StackPanel>
                    <Button x:Name="RefreshButton" DockPanel.Dock="Right" Content="REFRESH"
                            Background="#0B1120" Foreground="#E5E7EB" BorderBrush="#21F982"
                            FontFamily="Consolas" FontWeight="Bold" Padding="18,10" Margin="0,2,0,0"/>
                </DockPanel>

                <Grid Margin="0,0,0,16">
                    <Grid.ColumnDefinitions>
                        <ColumnDefinition Width="178"/>
                        <ColumnDefinition Width="300"/>
                        <ColumnDefinition Width="*"/>
                    </Grid.ColumnDefinitions>

                    <Grid Width="154" Height="154" ClipToBounds="True">
                        <Grid.Clip>
                            <EllipseGeometry Center="77,77" RadiusX="76" RadiusY="76"/>
                        </Grid.Clip>
                        <Ellipse Fill="#050F0C" Stroke="#21F982" StrokeThickness="2.2" Opacity="0.95"/>
                        <Ellipse Width="108" Height="108" Stroke="#18C46B" StrokeThickness="1" Opacity="0.55"/>
                        <Ellipse Width="58" Height="58" Stroke="#18C46B" StrokeThickness="1" Opacity="0.42"/>
                        <Line X1="77" Y1="11" X2="77" Y2="143" Stroke="#1EDB72" StrokeThickness="0.9" Opacity="0.45"/>
                        <Line X1="11" Y1="77" X2="143" Y2="77" Stroke="#1EDB72" StrokeThickness="0.9" Opacity="0.45"/>
                        <Path Opacity="0.48" Fill="#2DFF80" Stroke="#2DFF80" StrokeThickness="0.6">
                            <Path.Data>
                                <PathGeometry>
                                    <PathFigure StartPoint="77,77">
                                        <LineSegment Point="77,9"/>
                                        <ArcSegment Point="122,26" Size="68,68" SweepDirection="Clockwise"/>
                                        <LineSegment Point="77,77"/>
                                    </PathFigure>
                                </PathGeometry>
                            </Path.Data>
                            <Path.RenderTransform>
                                <RotateTransform x:Name="SweepRotate" Angle="0" CenterX="77" CenterY="77"/>
                            </Path.RenderTransform>
                        </Path>
                        <Ellipse Width="10" Height="10" Fill="#21F982" Stroke="#B8FFD6" StrokeThickness="1"/>
                        <TextBlock x:Name="LiveText" Text="IDLE" Foreground="#9CA3AF" FontFamily="Consolas"
                                   FontSize="15" FontWeight="Bold" HorizontalAlignment="Center"
                                   VerticalAlignment="Center"/>
                    </Grid>

                    <StackPanel Grid.Column="1" VerticalAlignment="Center" Margin="18,0,0,0">
                        <Grid Margin="0,0,0,8">
                            <Grid.ColumnDefinitions>
                                <ColumnDefinition Width="16"/>
                                <ColumnDefinition Width="70"/>
                                <ColumnDefinition Width="*"/>
                            </Grid.ColumnDefinitions>
                            <Ellipse Fill="#39FF14" Width="8" Height="8"/>
                            <TextBlock Grid.Column="1" Text="WIFI" Foreground="#9CA3AF" FontFamily="Consolas" FontSize="13"/>
                            <TextBlock x:Name="WifiCount" Grid.Column="2" Text="0" Foreground="#39FF14" FontFamily="Consolas" FontSize="16" FontWeight="Bold"/>
                        </Grid>
                        <Grid Margin="0,0,0,8">
                            <Grid.ColumnDefinitions>
                                <ColumnDefinition Width="16"/>
                                <ColumnDefinition Width="70"/>
                                <ColumnDefinition Width="*"/>
                            </Grid.ColumnDefinitions>
                            <Ellipse Fill="#00BFFF" Width="8" Height="8"/>
                            <TextBlock Grid.Column="1" Text="BT/BLE" Foreground="#9CA3AF" FontFamily="Consolas" FontSize="13"/>
                            <TextBlock x:Name="BluetoothCount" Grid.Column="2" Text="0" Foreground="#00BFFF" FontFamily="Consolas" FontSize="16" FontWeight="Bold"/>
                        </Grid>
                        <Grid Margin="0,0,0,8">
                            <Grid.ColumnDefinitions>
                                <ColumnDefinition Width="16"/>
                                <ColumnDefinition Width="70"/>
                                <ColumnDefinition Width="*"/>
                            </Grid.ColumnDefinitions>
                            <Ellipse Fill="#F59E0B" Width="8" Height="8"/>
                            <TextBlock Grid.Column="1" Text="CELL" Foreground="#9CA3AF" FontFamily="Consolas" FontSize="13"/>
                            <TextBlock x:Name="CellCount" Grid.Column="2" Text="0" Foreground="#F59E0B" FontFamily="Consolas" FontSize="16" FontWeight="Bold"/>
                        </Grid>
                        <Grid Margin="0,0,0,8">
                            <Grid.ColumnDefinitions>
                                <ColumnDefinition Width="16"/>
                                <ColumnDefinition Width="70"/>
                                <ColumnDefinition Width="*"/>
                            </Grid.ColumnDefinitions>
                            <Ellipse Fill="#8B5CF6" Width="8" Height="8"/>
                            <TextBlock Grid.Column="1" Text="SDR" Foreground="#9CA3AF" FontFamily="Consolas" FontSize="13"/>
                            <TextBlock x:Name="SdrCount" Grid.Column="2" Text="0" Foreground="#8B5CF6" FontFamily="Consolas" FontSize="16" FontWeight="Bold"/>
                        </Grid>
                        <Grid>
                            <Grid.ColumnDefinitions>
                                <ColumnDefinition Width="16"/>
                                <ColumnDefinition Width="70"/>
                                <ColumnDefinition Width="*"/>
                            </Grid.ColumnDefinitions>
                            <Ellipse Fill="#EF4444" Width="8" Height="8"/>
                            <TextBlock Grid.Column="1" Text="ALERTS" Foreground="#9CA3AF" FontFamily="Consolas" FontSize="13"/>
                            <TextBlock x:Name="AlertCount" Grid.Column="2" Text="0" Foreground="#EF4444" FontFamily="Consolas" FontSize="16" FontWeight="Bold"/>
                        </Grid>
                    </StackPanel>
                    <Border x:Name="AwarenessMapPanel" Grid.Column="2" HorizontalAlignment="Stretch" VerticalAlignment="Stretch"
                            Margin="24,0,0,0" Background="#660B1120" BorderBrush="#255866" BorderThickness="1"
                            CornerRadius="6" Padding="10" Cursor="Hand">
                        <Grid>
                            <Grid.ColumnDefinitions>
                                <ColumnDefinition Width="1.25*"/>
                                <ColumnDefinition Width="1*"/>
                            </Grid.ColumnDefinitions>
                            <Canvas x:Name="AwarenessMapCanvas" Background="#0B1120" ClipToBounds="True"/>
                            <StackPanel Grid.Column="1" Margin="12,0,0,0" VerticalAlignment="Center">
                                <TextBlock x:Name="AwarenessMapTitle" Text="AWARENESS TIMELINE" Foreground="#22D3EE"
                                           FontFamily="Consolas" FontSize="14" FontWeight="Bold"/>
                                <TextBlock x:Name="AwarenessMapSummary" Text="No signal profile yet" Foreground="#E5E7EB"
                                           FontFamily="Consolas" FontSize="18" FontWeight="Bold" Margin="0,8,0,0"/>
                                <TextBlock x:Name="AwarenessMapNormal" Text="Normal: 0" Foreground="#21F982"
                                           FontFamily="Consolas" FontSize="12" Margin="0,6,0,0"/>
                                <TextBlock x:Name="AwarenessMapOdd" Text="One-offs / changes: 0" Foreground="#F59E0B"
                                           FontFamily="Consolas" FontSize="12"/>
                                <TextBlock x:Name="AwarenessMapLast" Text="Click for timeline" Foreground="#9CA3AF"
                                           FontFamily="Consolas" FontSize="11" TextWrapping="Wrap" Margin="0,8,0,0"/>
                            </StackPanel>
                        </Grid>
                    </Border>
                </Grid>

                <Border Background="{StaticResource PanelBrush}" BorderBrush="#255866" BorderThickness="1" CornerRadius="6" Padding="12" Margin="0,0,0,10">
                    <Grid>
                        <Grid.ColumnDefinitions>
                            <ColumnDefinition Width="52"/>
                            <ColumnDefinition Width="*"/>
                        </Grid.ColumnDefinitions>
                        <Border Width="38" Height="38" Background="#1121F982" BorderBrush="#164E3A" BorderThickness="1" CornerRadius="5">
                            <Image x:Name="StatusIconImage" Width="34" Height="34"/>
                        </Border>
                        <StackPanel Grid.Column="1" Margin="10,0,0,0">
                            <TextBlock x:Name="SdrStatusText" Text="RTL-SDR READY" Foreground="#21F982"
                                       FontFamily="Consolas" FontWeight="Bold" FontSize="14"/>
                            <TextBlock Text="Start the Windows RTL server when the Android app needs RTL data. The endpoint below is what the phone connects to."
                                       Foreground="#8390A1" TextWrapping="Wrap" FontSize="12" Margin="0,4,0,0"/>
                            <TextBlock x:Name="EndpointText" Text="127.0.0.1:1234" Foreground="#22D3EE"
                                       FontFamily="Consolas" FontSize="17" FontWeight="Bold" Margin="0,7,0,0"/>
                        </StackPanel>
                    </Grid>
                </Border>

                <Button x:Name="ConnectButton" Content="START LOCAL RTL_TCP" Height="64"
                        Background="{StaticResource ButtonBlueBrush}" Foreground="White" BorderBrush="#0EA5E9"
                        FontFamily="Consolas" FontSize="18" FontWeight="Bold" Margin="0,0,0,12"/>

                <Button x:Name="StartRemoteServerButton" Content="OPEN RTL SERVER SCRIPT" Height="56"
                        Background="{StaticResource ButtonBlueBrush}" Foreground="White" BorderBrush="#0EA5E9"
                        FontFamily="Consolas" FontSize="17" FontWeight="Bold" Margin="0,0,0,12"/>

                <Grid Margin="0,0,0,16">
                    <Grid.ColumnDefinitions>
                        <ColumnDefinition Width="*"/>
                        <ColumnDefinition Width="12"/>
                        <ColumnDefinition Width="*"/>
                    </Grid.ColumnDefinitions>
                    <Button x:Name="TestButton" Content="TEST DONGLE" Grid.Column="0" Height="42"
                            Background="#111827" Foreground="#E5E7EB" BorderBrush="#255866"
                            FontFamily="Consolas" FontWeight="Bold"/>
                    <Button x:Name="OpenLogsButton" Content="OPEN LOGS" Grid.Column="2" Height="42"
                            Background="#111827" Foreground="#E5E7EB" BorderBrush="#255866"
                            FontFamily="Consolas" FontWeight="Bold"/>
                </Grid>

                <Button x:Name="RadioButton" Content="FM / AM RADIO TUNER" Height="48"
                        Background="{StaticResource ButtonGreenBrush}" Foreground="White" BorderBrush="#3B82F6"
                        FontFamily="Consolas" FontSize="15" FontWeight="Bold" Margin="0,0,0,16"/>

                <TextBlock Text="SCANNERS" Foreground="#9CA3AF" FontFamily="Consolas"
                           FontSize="12" Margin="0,0,0,10"/>

                <UniformGrid Columns="2" Rows="3" Margin="0,0,0,16">
                    <Border x:Name="WifiTile" Cursor="Hand" Background="{StaticResource PanelBrush}" BorderBrush="#255866" BorderThickness="1" CornerRadius="6" Padding="12" Margin="0,0,6,6">
                        <StackPanel>
                            <TextBlock x:Name="WifiTileCount" Text="0" Foreground="#39FF14" FontFamily="Consolas" FontSize="28" FontWeight="Bold"/>
                            <TextBlock Text="WIFI" Foreground="#9CA3AF" FontFamily="Consolas" FontSize="12"/>
                            <TextBlock Tag="Condensed" Text="Windows WLAN scan" Foreground="#6B7280" FontSize="12"/>
                        </StackPanel>
                    </Border>
                    <Border x:Name="BluetoothTile" Cursor="Hand" Background="{StaticResource PanelBrush}" BorderBrush="#255866" BorderThickness="1" CornerRadius="6" Padding="12" Margin="6,0,0,6">
                        <StackPanel>
                            <TextBlock x:Name="BluetoothTileCount" Text="0" Foreground="#00BFFF" FontFamily="Consolas" FontSize="28" FontWeight="Bold"/>
                            <TextBlock Text="BLUETOOTH" Foreground="#9CA3AF" FontFamily="Consolas" FontSize="12"/>
                            <TextBlock Tag="Condensed" Text="Paired/adapter devices" Foreground="#6B7280" FontSize="12"/>
                        </StackPanel>
                    </Border>
                    <Border x:Name="NfcTile" Cursor="Hand" Background="{StaticResource PanelBrush}" BorderBrush="#255866" BorderThickness="1" CornerRadius="6" Padding="12" Margin="0,6,6,6">
                        <StackPanel>
                            <TextBlock x:Name="NfcTileCount" Text="0" Foreground="#EC4899" FontFamily="Consolas" FontSize="28" FontWeight="Bold"/>
                            <TextBlock Text="NFC" Foreground="#9CA3AF" FontFamily="Consolas" FontSize="12"/>
                            <TextBlock Tag="Condensed" Text="Unavailable on this PC" Foreground="#6B7280" FontSize="12"/>
                        </StackPanel>
                    </Border>
                    <Border x:Name="CellTile" Cursor="Hand" Background="{StaticResource PanelBrush}" BorderBrush="#255866" BorderThickness="1" CornerRadius="6" Padding="12" Margin="6,6,0,6">
                        <StackPanel>
                            <TextBlock x:Name="CellTileCount" Text="0" Foreground="#F59E0B" FontFamily="Consolas" FontSize="28" FontWeight="Bold"/>
                            <TextBlock Text="CELLULAR" Foreground="#9CA3AF" FontFamily="Consolas" FontSize="12"/>
                            <TextBlock Tag="Condensed" Text="Phone-only scanner" Foreground="#6B7280" FontSize="12"/>
                        </StackPanel>
                    </Border>
                    <Border x:Name="SdrTile" Cursor="Hand" Background="{StaticResource PanelBrush}" BorderBrush="#255866" BorderThickness="1" CornerRadius="6" Padding="12" Margin="0,6,6,0">
                        <StackPanel>
                            <TextBlock x:Name="SdrTileCount" Text="0" Foreground="#8B5CF6" FontFamily="Consolas" FontSize="28" FontWeight="Bold"/>
                            <TextBlock Text="SDR RADIO" Foreground="#9CA3AF" FontFamily="Consolas" FontSize="12"/>
                            <TextBlock Tag="Condensed" x:Name="LocalIpText" Text="127.0.0.1:1234" Foreground="#6B7280" FontFamily="Consolas" FontSize="12"/>
                        </StackPanel>
                    </Border>
                    <Border x:Name="AlertTile" Cursor="Hand" Background="{StaticResource PanelBrush}" BorderBrush="#255866" BorderThickness="1" CornerRadius="6" Padding="12" Margin="6,6,0,0">
                        <StackPanel>
                            <TextBlock x:Name="AlertTileCount" Text="0" Foreground="#EF4444" FontFamily="Consolas" FontSize="28" FontWeight="Bold"/>
                            <TextBlock Text="ALERTS" Foreground="#9CA3AF" FontFamily="Consolas" FontSize="12"/>
                            <TextBlock Tag="Condensed" Text="Local app status only" Foreground="#6B7280" FontSize="12"/>
                        </StackPanel>
                    </Border>
                </UniformGrid>

                <TextBlock Text="DETECTED SIGNALS" Foreground="#9CA3AF" FontFamily="Consolas"
                           FontSize="12" Margin="0,0,0,10"/>
                <DataGrid Tag="Condensed" x:Name="MainSignalGrid" MinHeight="180" MaxHeight="260" Margin="0,0,0,16"
                          AutoGenerateColumns="True" IsReadOnly="True" CanUserAddRows="False"
                          CanUserDeleteRows="False" GridLinesVisibility="Horizontal"
                          Background="#0B1120" Foreground="#E5E7EB"
                          RowBackground="#111827" AlternatingRowBackground="#0F172A"
                          BorderBrush="#374151" FontFamily="Consolas" FontSize="12"/>

                <TextBox Tag="Condensed" x:Name="LogBox" MinHeight="160" Background="#0B1120" Foreground="#D1D5DB"
                         BorderBrush="#374151" FontFamily="Consolas" FontSize="12"
                         TextWrapping="Wrap" VerticalScrollBarVisibility="Auto" IsReadOnly="True"/>
            </StackPanel>
            </Border>
        </Grid>
    </ScrollViewer>
</Window>
"@

$reader = New-Object System.Xml.XmlNodeReader $xaml
$Window = [Windows.Markup.XamlReader]::Load($reader)
Set-SnifferOpsWindowIcon -TargetWindow $Window

# Safety net: log any unhandled UI-thread exception and keep the app alive.
$Window.Dispatcher.add_UnhandledException({
    param($eventSender, $eventArgs)
    Write-CrashLog -Context "WPF dispatcher" -ErrorObject $eventArgs.Exception
    $eventArgs.Handled = $true
})
$Window.Add_Loaded({
    Apply-SnifferOpsFont -Root $Window
    Apply-SnifferOpsSpecialFonts -Root $Window
})

$ConnectButton = $Window.FindName("ConnectButton")
$StartRemoteServerButton = $Window.FindName("StartRemoteServerButton")
$TestButton = $Window.FindName("TestButton")
$OpenLogsButton = $Window.FindName("OpenLogsButton")
$RadioButton = $Window.FindName("RadioButton")
$RefreshButton = $Window.FindName("RefreshButton")
$HeaderIconImage = $Window.FindName("HeaderIconImage")
$StatusIconImage = $Window.FindName("StatusIconImage")
$LogBox = $Window.FindName("LogBox")
$LiveText = $Window.FindName("LiveText")
$SdrStatusText = $Window.FindName("SdrStatusText")
$EndpointText = $Window.FindName("EndpointText")
$LocalIpText = $Window.FindName("LocalIpText")
$WifiCount = $Window.FindName("WifiCount")
$BluetoothCount = $Window.FindName("BluetoothCount")
$CellCount = $Window.FindName("CellCount")
$SdrCount = $Window.FindName("SdrCount")
$AlertCount = $Window.FindName("AlertCount")
$WifiTileCount = $Window.FindName("WifiTileCount")
$BluetoothTileCount = $Window.FindName("BluetoothTileCount")
$NfcTileCount = $Window.FindName("NfcTileCount")
$CellTileCount = $Window.FindName("CellTileCount")
$SdrTileCount = $Window.FindName("SdrTileCount")
$AlertTileCount = $Window.FindName("AlertTileCount")
$WifiTile = $Window.FindName("WifiTile")
$BluetoothTile = $Window.FindName("BluetoothTile")
$NfcTile = $Window.FindName("NfcTile")
$CellTile = $Window.FindName("CellTile")
$SdrTile = $Window.FindName("SdrTile")
$AlertTile = $Window.FindName("AlertTile")
$MainSignalGrid = $Window.FindName("MainSignalGrid")
$AwarenessMapPanel = $Window.FindName("AwarenessMapPanel")
$AwarenessMapCanvas = $Window.FindName("AwarenessMapCanvas")
$AwarenessMapTitle = $Window.FindName("AwarenessMapTitle")
$AwarenessMapSummary = $Window.FindName("AwarenessMapSummary")
$AwarenessMapNormal = $Window.FindName("AwarenessMapNormal")
$AwarenessMapOdd = $Window.FindName("AwarenessMapOdd")
$AwarenessMapLast = $Window.FindName("AwarenessMapLast")
$SweepRotate = $Window.FindName("SweepRotate")

Set-SnifferOpsImageSource -TargetImage $HeaderIconImage
Set-SnifferOpsImageSource -TargetImage $StatusIconImage
Apply-SnifferOpsFont -Root $Window
Apply-SnifferOpsSpecialFonts -Root $Window

$ConnectButton.Add_Click({
    Invoke-AppAction -Context "Toggle rtl_tcp" -Action {
        if (Get-Process rtl_tcp -ErrorAction SilentlyContinue) {
            Stop-RtlTcpServer
        } else {
            Start-RtlTcpServer
        }
    }
})

$StartRemoteServerButton.Add_Click({
    Invoke-AppAction -Context "Start Windows RTL server" -Action {
        Start-RemoteRtlServerFromScript
    }
})

$TestButton.Add_Click({ Invoke-AppAction -Context "Test dongle" -Action { Test-RtlSdrDongle } })
$RadioButton.Add_Click({ Invoke-AppAction -Context "Open radio tuner" -Action { Show-RadioTunerWindow } })
$RefreshButton.Add_Click({
    Invoke-AppAction -Context "Refresh scanner counts" -Action {
        Refresh-ScannerCounts
        Add-LogLine "Refreshed local scanner counts."
    }
})
$OpenLogsButton.Add_Click({
    Invoke-AppAction -Context "Open logs" -Action {
        if (Test-Path $ErrLog) {
            Start-Process notepad.exe $ErrLog
        } else {
            Add-LogLine "No rtl_tcp error log exists yet."
        }
    }
})

$WifiTile.Add_MouseLeftButtonUp({
    Invoke-AppAction -Context "Open WiFi details" -Action {
        Show-DetailWindow -Title "WiFi Scanner" -Accent "#39FF14" -Items @(Get-WifiDetails)
    }
})
$BluetoothTile.Add_MouseLeftButtonUp({
    Invoke-AppAction -Context "Open Bluetooth details" -Action {
        Show-DetailWindow -Title "Bluetooth Scanner" -Accent "#00BFFF" -Items @(Get-BluetoothDetails)
    }
})
$NfcTile.Add_MouseLeftButtonUp({
    Invoke-AppAction -Context "Open NFC details" -Action {
        Show-DetailWindow -Title "NFC Scanner" -Accent "#EC4899" -Items @(Get-UnavailableDetails -Name "NFC reader" -Reason "The Windows app cannot read NFC without dedicated NFC hardware and a Windows reader driver. The phone app remains the NFC scanner.")
    }
})
$CellTile.Add_MouseLeftButtonUp({
    Invoke-AppAction -Context "Open cellular details" -Action {
        Show-DetailWindow -Title "Cellular Scanner" -Accent "#F59E0B" -Items @(Get-UnavailableDetails -Name "Cellular tower scan" -Reason "Cell tower APIs are exposed by Android on the phone. This Windows machine does not expose comparable tower scan data.")
    }
})
$SdrTile.Add_MouseLeftButtonUp({
    Invoke-AppAction -Context "Open SDR details" -Action {
        Show-DetailWindow -Title "SDR Radio" -Accent "#8B5CF6" -Items @(Get-SdrDetails)
    }
})
$AlertTile.Add_MouseLeftButtonUp({
    Invoke-AppAction -Context "Open alerts details" -Action {
        Show-DetailWindow -Title "Signal Alerts + Awareness" -Accent "#EF4444" -Items @(Get-AlertDetails)
    }
})
$AwarenessMapPanel.Add_MouseLeftButtonUp({
    Invoke-AppAction -Context "Open awareness locations" -Action {
        Show-AwarenessLocationWindow
    }
})
$MainSignalGrid.Add_MouseDoubleClick({
    Invoke-AppAction -Context "Main signal details" -Action {
        $row = $MainSignalGrid.SelectedItem
        if (-not $row) { return }

        if ($row.Type -eq "SDR") {
            $match = @($script:SdrSignals | Where-Object { $_.Frequency -eq $row.AddressOrFrequency } | Select-Object -First 1)
            if ($match.Count -gt 0) {
                Show-SignalDetailWindow -Title "Detected Signals" -Accent "#8B5CF6" -Item $match[0]
                return
            }
        }

        Show-SignalDetailWindow -Title "Detected Signals" -Accent "#39FF14" -Item $row
    }
})

$script:ScanTimer = New-Object Windows.Threading.DispatcherTimer
$script:ScanTimer.Interval = [TimeSpan]::FromSeconds(4)
$script:ScanTimer.Add_Tick({
    Invoke-AppAction -Context "Auto refresh" -Action {
        [void](Receive-AwarenessSyncRequests -LogPath $AppLog)
        Refresh-ScannerCounts
    }
})
$script:ScanTimer.Start()

$script:SweepTimer = New-Object Windows.Threading.DispatcherTimer
$script:SweepTimer.Interval = [TimeSpan]::FromMilliseconds(40)
$script:SweepTimer.Add_Tick({
    if ($script:ScanActive) {
        $script:SweepAngle = ($script:SweepAngle + 4) % 360
        $SweepRotate.Angle = $script:SweepAngle
    }
})
$script:SweepTimer.Start()

$Window.Add_Closed({
    if ($script:ScanTimer) { $script:ScanTimer.Stop() }
    if ($script:SweepTimer) { $script:SweepTimer.Stop() }
    Stop-AwarenessSyncServer
    Stop-SdrAudio -RestoreServer:$false
})

Invoke-AppAction -Context "Startup refresh" -Action {
    try {
        Start-AwarenessSyncServer -BindAddress $BindAddress -Port $AwarenessSyncPort -LogPath $AppLog
        Add-LogLine "Awareness sync listening at http://$(Get-LanIpAddress):$AwarenessSyncPort/snifferops/sync"
    } catch {
        Add-LogLine "Awareness sync unavailable: $($_.Exception.Message)"
    }
    Refresh-ScannerCounts
    Add-LogLine "SnifferOps Windows ready."
    Add-LogLine "Click START WINDOWS RTL SERVER when the Android app needs RTL data."
}

if ($SmokeTest) {
    Write-Host "SnifferOps Windows smoke test OK"
    return
}

[void] $Window.ShowDialog()
