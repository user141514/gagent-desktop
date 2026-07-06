@echo off
chcp 65001 >nul
title 微信数据库解密工具
cd /d "%~dp0"
echo.
echo ============================================
echo   微信数据库解密工具
echo ============================================
echo.
echo 用法:
echo   python wechat_decrypt.py --list         列出数据库和表
echo   python wechat_decrypt.py --bruteforce   暴力搜索密钥
echo   python wechat_decrypt.py --key HEX_KEY  手动密钥解密
echo   python wechat_decrypt.py --help         查看完整帮助
echo.
echo 快捷操作:
echo   [1] 暴力搜索密钥 + 解密全部
echo   [2] 仅列出数据库和表
echo   [3] 手动输入密钥解密
echo   [4] 退出
echo.
set /p choice="请选择 (1-4): "
if "%choice%"=="1" python wechat_decrypt.py --bruteforce
if "%choice%"=="2" python wechat_decrypt.py --list
if "%choice%"=="3" (
    set /p key="请输入64位hex密钥: "
    python wechat_decrypt.py --key !key!
)
if "%choice%"=="4" exit
pause
