@echo off
> "%TEMP%\dg_dp.txt" echo %~dp0
> "%TEMP%\dg_cd.txt" echo %CD%
"%~dp0..\..\..\..\AppData\Local\Programs\Python\Python39\python.exe" -c "import sys,os;open(os.environ['TEMP']+'\\dg_py.txt','w',encoding='utf-8').write(sys.argv[1]+'\n'+os.getcwd())" "%~f0"
