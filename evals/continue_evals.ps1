param([int]$InitialProcessId = 0)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
$taskPython = (Get-Command python -ErrorAction Stop).Source
$taskLogs = Join-Path $taskRoot 'eval_results_resume'
New-Item -ItemType Directory -Path $taskLogs -Force | Out-Null
$env:GROQ_RETRY_BUDGET = '7200'
$env:GROQ_MIN_INTERVAL = '10'
$env:PYTHONIOENCODING = 'utf-8'

function Write-ProgressLog([string]$Message) {
    Write-Output ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' ' + $Message)
}

try {
    if ($InitialProcessId -gt 0) {
        Write-ProgressLog ('Waiting for existing evaluation PID ' + $InitialProcessId)
        if (Get-Process -Id $InitialProcessId -ErrorAction SilentlyContinue) {
            Wait-Process -Id $InitialProcessId -ErrorAction SilentlyContinue
        }
    }
    $pass = 0
    while ($true) {
        $report = Get-Content -Encoding UTF8 -Raw -LiteralPath (Join-Path $taskRoot 'eval_after.json') | ConvertFrom-Json
        $config = $report.config
        if ($config.provider -ne 'groq' -or $config.model -ne 'openai/gpt-oss-20b' -or
            $config.judge_provider -ne 'groq' -or $config.judge_model -ne 'openai/gpt-oss-20b' -or
            $config.max_steps -ne 8 -or $config.dataset -ne 'core' -or $report.cases.Count -ne 22) {
            throw 'Configuration changed; refusing to mix evaluation settings.'
        }
        $scored = @($report.cases | Where-Object { $_.grade.status -eq 'scored' -and $null -ne $_.grade.score }).Count
        Write-ProgressLog ('Saved progress: ' + $scored + '/22 scored.')
        if ($scored -eq 22 -and $null -ne $report.summary.score_0_100) {
            Write-ProgressLog ('COMPLETE. Score: ' + $report.summary.score_0_100 + '/100. File: eval_after.json')
            exit 0
        }
        $fatalAuthentication = @($report.cases | Where-Object {
            $_.grade.status -ne 'scored' -and @($_.result.trace | Where-Object {
                $_.event -eq 'provider_error' -and $_.http_status -in @(401,403)
            }).Count -gt 0
        }).Count
        if ($fatalAuthentication -gt 0) {
            throw 'API authentication/permission failed; stopping retries until configuration is fixed.'
        }
        $pass += 1
        Write-ProgressLog ('Waiting 600 seconds before resume pass ' + $pass)
        Start-Sleep -Seconds 600
        $prefix = Join-Path $taskLogs ('pass_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
        Write-ProgressLog ('Starting resume pass ' + $pass + '; logs: ' + $prefix)
        $taskProcess = Start-Process -FilePath $taskPython -ArgumentList @(
            '-B','-u','evals/run_evals.py','--provider','groq','--model','openai/gpt-oss-20b',
            '--judge-provider','groq','--judge-model','openai/gpt-oss-20b',
            '--max-steps','8','--workers','1','--output','eval_after.json','--resume'
        ) -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput ($prefix + '.stdout.log') -RedirectStandardError ($prefix + '.stderr.log') -PassThru -Wait
        Write-ProgressLog ('Resume pass ended with exit code ' + $taskProcess.ExitCode)
    }
} catch {
    Write-ProgressLog ('STOPPED: ' + $_.Exception.Message)
    exit 1
}
