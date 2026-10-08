@echo off
rem Re-assemble the portable BTRun distribution after a PyInstaller build
rem (PyInstaller wipes dist\BTRun on every rebuild, so the bundled data must
rem be re-copied each time).  Run from the LLM_BT_Gen folder.  This script
rem itself contains only ASCII text.
setlocal
set DIST=%~dp0dist\BTRun
set ROOT=%~dp0..

xcopy /e /i /y "%ROOT%\NuSMV-2.7.1-win64\NuSMV-2.7.1-win64" "%DIST%\NuSMV" >nul
if not exist "%DIST%\benchmarks" mkdir "%DIST%\benchmarks"
copy /y "%ROOT%\behaverify\Benchmark\Behaverify_benchmark_hard.xlsx" "%DIST%\benchmarks\" >nul
copy /y "%~dp0complex_tasks.xlsx" "%DIST%\benchmarks\" >nul
copy /y "%~dp0prompt_behaverify.txt" "%DIST%\" >nul
if not exist "%DIST%\selftest" mkdir "%DIST%\selftest"
copy /y "%ROOT%\behaverify\Benchmark\trees\ABC3.tree" "%DIST%\selftest\selftest.tree" >nul
copy /y "%~dp0README_dist.txt" "%DIST%\README.txt" >nul

echo Distribution assembled:
dir /b "%DIST%"
endlocal
