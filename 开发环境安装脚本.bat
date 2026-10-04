@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo            CDTV 漫剧自动化客户端 - 环境安装向导
echo ============================================================
echo.
echo 本脚本会自动完成以下步骤：
echo   1. 检查 Python 和 Node.js 是否已安装
echo   2. 创建 Python 虚拟环境 (.venv)
echo   3. 安装 Python 依赖
echo   4. 安装前端依赖并构建
echo.
echo 整个过程需要联网，请耐心等待，不要关闭本窗口。
echo.
pause

rem ============================================================
rem 第 1 步：检查 Python
rem ============================================================
echo.
echo [1/4] 正在检查 Python...
where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo [错误] 未检测到 Python。
  echo 请先到 https://www.python.org/downloads/ 下载安装 Python 3.11 或更高版本。
  echo 安装时务必勾选 "Add Python to PATH"。
  goto :fail
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo       已检测到 Python !PYVER!

rem ============================================================
rem 第 2 步：检查 Node.js
rem ============================================================
echo.
echo [2/4] 正在检查 Node.js...
where node >nul 2>nul
if errorlevel 1 (
  echo.
  echo [错误] 未检测到 Node.js。
  echo 请先到 https://nodejs.org/ 下载安装 LTS 版本（20.19+ 或 22.12+）。
  goto :fail
)

for /f "tokens=*" %%v in ('node --version 2^>^&1') do set NODEVER=%%v
echo       已检测到 Node.js !NODEVER!

rem ============================================================
rem 第 3 步：创建虚拟环境并安装 Python 依赖
rem ============================================================
echo.
echo [3/4] 正在准备 Python 虚拟环境...
if exist ".venv\Scripts\python.exe" (
  echo       虚拟环境已存在，跳过创建。
) else (
  echo       正在创建 .venv ...
  python -m venv .venv
  if errorlevel 1 (
    echo.
    echo [错误] 创建虚拟环境失败。
    goto :fail
  )
  echo       虚拟环境创建完成。
)

echo.
echo       正在安装 Python 依赖 (requirements.txt)...
echo       这一步可能需要几分钟，请勿关闭窗口。
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo [错误] Python 依赖安装失败，请检查网络连接后重试。
  goto :fail
)
echo       Python 依赖安装完成。

rem ============================================================
rem 第 4 步：安装前端依赖并构建
rem ============================================================
echo.
echo [4/4] 正在安装前端依赖...
pushd frontend
if exist "node_modules" (
  echo       前端依赖已存在，跳过安装。
) else (
  call npm ci
  if errorlevel 1 (
    echo       未使用锁文件安装成功，尝试普通安装...
    call npm install
    if errorlevel 1 (
      popd
      echo.
      echo [错误] 前端依赖安装失败，请检查网络连接后重试。
      goto :fail
    )
  )
)

echo.
echo       正在构建前端 (npm run build)...
call npm run build
if errorlevel 1 (
  popd
  echo.
  echo [错误] 前端构建失败。
  goto :fail
)
popd
echo       前端构建完成。

rem ============================================================
rem 完成
rem ============================================================
echo.
echo ============================================================
echo                    环境安装完成！
echo ============================================================
echo.
echo 现在可以双击 "启动应用.bat" 启动客户端了。
echo.
pause
exit /b 0

:fail
echo.
echo ============================================================
echo   安装未完成，请根据上面的提示解决问题后重新运行本脚本。
echo ============================================================
echo.
pause
exit /b 1
