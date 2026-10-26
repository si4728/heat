param(
    [datetime]$ReportTime = (Get-Date),
    [string]$ProjectRootPath = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = if ([string]::IsNullOrWhiteSpace($ProjectRootPath)) {
    Split-Path -Parent (Split-Path -Parent $PSCommandPath)
} else {
    $ProjectRootPath
}
$reportDirectory = Join-Path $projectRoot "docs\weekly_reports"
$currentMonday = $ReportTime.Date.AddDays(-(([int]$ReportTime.DayOfWeek + 6) % 7))
$periodStart = $currentMonday.AddDays(-7)
$periodEnd = $ReportTime
$reportPath = Join-Path $reportDirectory ("주간보고서_{0}.docx" -f $periodEnd.ToString("yyyy-MM-dd"))
$temporaryDirectory = Join-Path $projectRoot "tmp\weekly_report"
$temporaryMarkdownPath = Join-Path $temporaryDirectory ("주간보고서_{0}.md" -f $periodEnd.ToString("yyyy-MM-dd"))

New-Item -ItemType Directory -Path $reportDirectory -Force | Out-Null
New-Item -ItemType Directory -Path $temporaryDirectory -Force | Out-Null

function Convert-ToRelativePath([string]$Path) {
    $rootWithSeparator = $projectRoot.TrimEnd("\") + "\"
    if ($Path.StartsWith($rootWithSeparator, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $Path.Substring($rootWithSeparator.Length).Replace("\", "/")
    }
    return $Path.Replace("\", "/")
}

$includedExtensions = @(".py", ".js", ".css", ".html", ".md", ".sql", ".ps1", ".cmd", ".conf", ".json", ".txt")

$changedFiles = Get-ChildItem -LiteralPath $projectRoot -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object {
        $fullName = $_.FullName
        $relativeName = Convert-ToRelativePath $fullName
        $excluded = $relativeName -match '(^|/)(\.pytest_cache|__pycache__|backups|tmp|uploads|outputs|iris_test_report|data|docs/weekly_reports)(/|$)'
        -not $excluded -and
        $includedExtensions -contains $_.Extension.ToLowerInvariant() -and
        $_.LastWriteTime -ge $periodStart -and $_.LastWriteTime -le $periodEnd
    } |
    Sort-Object LastWriteTime -Descending

$workstreams = New-Object System.Collections.Generic.List[string]
foreach ($file in $changedFiles) {
    $relative = Convert-ToRelativePath $file.FullName
    switch -Regex ($relative) {
        "tube[_-]map|three|OrbitControls|TransformControls" { $workstreams.Add("2D/3D 튜브맵 및 부식 시각화 개선"); break }
        "remaining[_-]life|life[_-]prediction|pressure[_-]vessel|api510" { $workstreams.Add("잔여수명·API 510 계산 및 건전성 평가"); break }
        "import|json|mapping|validator|master_heat" { $workstreams.Add("IRIS·설비 마스터 데이터 수집, 정규화 및 검증"); break }
        "database|models|schema|migration|backup" { $workstreams.Add("데이터베이스 구조·무결성·백업 관리"); break }
        "maintenance|work[_-]order|inspection[_-]plan" { $workstreams.Add("검사계획·정비·작업지시 업무 흐름"); break }
        "auth|user|security|login" { $workstreams.Add("사용자 인증 및 보안 관리"); break }
        "test" { $workstreams.Add("회귀 테스트 및 품질 검증"); break }
        "docs/|README|IMPLEMENTATION" { $workstreams.Add("기술 문서 및 운영 기준 정비"); break }
        default { $workstreams.Add("애플리케이션 기능 및 운영 안정성 개선") }
    }
}
$workstreams = @($workstreams | Select-Object -Unique)

$codeCategories = @(
    [pscustomobject]@{ Label = "Python"; Extensions = @(".py"); Display = ".py" },
    [pscustomobject]@{ Label = "HTML 템플릿"; Extensions = @(".html"); Display = ".html" },
    [pscustomobject]@{ Label = "JavaScript"; Extensions = @(".js"); Display = ".js" },
    [pscustomobject]@{ Label = "CSS 스타일"; Extensions = @(".css"); Display = ".css" },
    [pscustomobject]@{ Label = "Markdown 문서"; Extensions = @(".md"); Display = ".md" },
    [pscustomobject]@{ Label = "SQL"; Extensions = @(".sql"); Display = ".sql" },
    [pscustomobject]@{ Label = "실행 스크립트"; Extensions = @(".ps1", ".cmd"); Display = ".ps1, .cmd" },
    [pscustomobject]@{ Label = "설정·데이터 정의"; Extensions = @(".conf", ".json", ".txt"); Display = ".conf, .json, .txt" }
)

$databaseSummary = $null
$databaseSummaryHelper = Join-Path $projectRoot "tools\weekly_report_db_summary.py"
if (Test-Path -LiteralPath $databaseSummaryHelper) {
    try {
        $summaryJson = & python $databaseSummaryHelper `
            --project-root $projectRoot `
            --start $periodStart.ToString("s") `
            --end $periodEnd.ToString("s")
        if ($LASTEXITCODE -eq 0 -and $summaryJson) {
            $databaseSummary = $summaryJson | ConvertFrom-Json
        }
    } catch {
        $databaseSummary = $null
    }
}

$nextPlans = New-Object System.Collections.Generic.List[string]
if ($workstreams -match "튜브맵") {
    $nextPlans.Add("실제 Tube Sheet X/Y 좌표와 방향 기준의 원천 데이터 연결 및 화면 대조")
    $nextPlans.Add("원주각·결함 길이 데이터 확보 시 2D 펼침도와 3D 국부 패치 표시 검증")
    $nextPlans.Add("단일 튜브 회전·확대·이동과 모바일 조작 회귀 테스트")
}
if ($workstreams -match "데이터") {
    $nextPlans.Add("미매핑·불일치 원천 데이터 검토와 검증된 항목의 단계적 반영")
}
if ($workstreams -match "잔여수명|API 510") {
    $nextPlans.Add("계산 입력값의 출처와 단위 검증 및 경계조건 테스트 보강")
}
if ($workstreams -match "데이터베이스|백업") {
    $nextPlans.Add("DB quick_check, 외래키 무결성 및 복구 가능한 백업 상태 확인")
}
$nextPlans.Add("변경 기능 중심 회귀 테스트 수행 및 사용자 확인사항 반영")
$nextPlans.Add("완료 기능·잔여 데이터 제한사항을 운영 문서와 일치하도록 갱신")
$nextPlans = @($nextPlans | Select-Object -Unique | Select-Object -First 6)

$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# 지능형열교환기 시스템 주간보고서")
$lines.Add("")
$lines.Add("- 프로젝트명: 지능형열교환기 시스템 · 보고 기준일: $($periodEnd.ToString('yyyy-MM-dd HH:mm'))")
$lines.Add("- 대상 기간: $($periodStart.ToString('yyyy-MM-dd HH:mm')) ~ $($periodEnd.ToString('yyyy-MM-dd HH:mm'))")
$lines.Add("- 작성 주기: 매주 월요일 10:00")
$lines.Add("- 변경 파일: $($changedFiles.Count)개")
$lines.Add("")
$lines.Add("## 1. 금주 진행 요약")
$lines.Add("")
if ($workstreams.Count -eq 0) {
    $lines.Add("- 대상 기간에 확인된 소스·문서 변경사항이 없습니다.")
} else {
    foreach ($item in $workstreams) { $lines.Add("- $item") }
}
$lines.Add("")
$lines.Add("## 2. 주요 변경사항")
$lines.Add("")
if ($changedFiles.Count -eq 0) {
    $lines.Add("변경 파일이 없습니다.")
} else {
    $lines.Add("| 코드 분류 | 확장자 | 변경 건수 |")
    $lines.Add("|---|---|---:|")
    foreach ($category in $codeCategories) {
        $count = @($changedFiles | Where-Object { $category.Extensions -contains $_.Extension.ToLowerInvariant() }).Count
        if ($count -gt 0) {
            $lines.Add("| $($category.Label) | ``$($category.Display)`` | $($count)건 |")
        }
    }
    $lines.Add("| **합계** |  | **$($changedFiles.Count)건** |")
}
$lines.Add("")
$lines.Add("## 3. PDF·C-Scan 연동 및 DB 반영 현황")
$lines.Add("")
if ($null -eq $databaseSummary -or -not $databaseSummary.available) {
    $lines.Add("- 운영 데이터베이스를 확인할 수 없어 연동 현황을 집계하지 못했습니다.")
} else {
    $periodUpdateText = if ($databaseSummary.database_modified_in_period) { "기간 내 변경 확인" } else { "기간 내 파일 변경 없음" }
    $lines.Add("- DB 상태: $periodUpdateText · Database명 $($databaseSummary.database_name) · 최종 변경 $($databaseSummary.database_modified_at)")
    $lines.Add("- 기간 내 추적 가능한 적재 작업: $($databaseSummary.period_import_batches)건 · 적재 보고서 $($databaseSummary.period_loaded_reports)건 · 경고 $($databaseSummary.period_import_warnings)건 · 오류 $($databaseSummary.period_import_errors)건")
    $lines.Add("")
    $lines.Add("| 연동 구분 | DB 반영·연결 내용 | 건수 |")
    $lines.Add("|---|---|---:|")
    $lines.Add("| PDF | 튜브 검사결과의 원본 페이지 연결 | $($databaseSummary.pdf_result_page_links)건 |")
    $lines.Add("| PDF | 검사별 페이지 역할 연결 | $($databaseSummary.pdf_inspection_page_links)건 |")
    $lines.Add("| PDF | 원본 페이지가 연결된 검사 | $($databaseSummary.pdf_linked_inspections)건 |")
    $lines.Add("| PDF | 이미지가 포함된 원본 페이지 | $($databaseSummary.pdf_pages_with_images)건 |")
    $lines.Add("| PDF/첨부 | 첨부자료 존재 확인 | $($databaseSummary.attachment_records)건 |")
    $lines.Add("| C-Scan·원시데이터 | 개별 결함 지시 DB 반영 | $($databaseSummary.indication_records)건 |")
    $lines.Add("| C-Scan·원시데이터 | 원시 데이터 경로 연결 | $($databaseSummary.raw_data_path_links)건 |")
    $lines.Add("| C-Scan·원시데이터 | 취득 시각 연결 | $($databaseSummary.acquisition_time_links)건 |")
    $lines.Add("| C-Scan 이미지 | 직접 이미지·페이지 참조 연결 | $($databaseSummary.cscan_image_links)건 |")
    $lines.Add("| C-Scan 측정값 | 최소 두께 직접 반영 | $($databaseSummary.cscan_thickness_values)건 |")
    $lines.Add("")
    $lines.Add("- 기간별 적재 건수는 기록 시각이 있는 적재 작업만 집계하며, 생성·수정 시각이 없는 상세 결과 테이블은 현재 누계로 표시합니다.")
}
$lines.Add("")
$lines.Add("## 4. 품질·리스크 및 확인 필요사항")
$lines.Add("")
$lines.Add("- 원본 검사값과 DB 값은 임의 보정하지 않고 출처와 데이터 수준을 구분해야 합니다.")
$lines.Add("- Tube Sheet 좌표, 축 기준방향, 원주각 및 결함 길이가 없는 경우 화면에는 대표값 또는 미확정 상태로 표시해야 합니다.")
$lines.Add("- DB, 업로드, 백업, 임시 산출물은 보고서 변경 파일 집계에서 제외했습니다.")
$lines.Add("")
$lines.Add("## 5. 차주 계획")
$lines.Add("")
foreach ($plan in $nextPlans) { $lines.Add("- $plan") }

$lines | Set-Content -LiteralPath $temporaryMarkdownPath -Encoding UTF8
$sampleBuilder = Join-Path $projectRoot "tools\generate_tube_map_samples.py"
& python $sampleBuilder | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Tube Map sample generation failed."
}
$docxBuilder = Join-Path $projectRoot "tools\weekly_report_docx.py"
& python $docxBuilder --input $temporaryMarkdownPath --output $reportPath
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $reportPath)) {
    throw "Word weekly report generation failed."
}
Remove-Item -LiteralPath $temporaryMarkdownPath -Force
Write-Output $reportPath
