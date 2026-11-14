@echo off
setlocal
echo [probe] start
python -V
python -c "import yaml,sys; print(chr(121)+chr(97)+chr(109)+chr(108), yaml.__version__, sys.executable)"
python "%~dp0..\scripts\guard.py" gate --manifest "%~dp0..\examples\case_pending\materials.yaml" --src "%~dp0..\examples\case_pending\raw" --out "%TEMP%\dg39b"
echo [probe] exit=%ERRORLEVEL%
