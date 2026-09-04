@echo off
rem Launcher for the ASUS Router Control MCP Bundle on Windows.
rem See launch.sh for why the bundle looks for an externally installed server.
setlocal enabledelayedexpansion

for %%C in (
    "%ASUSWRT_MCP_BIN%"
    "%ASUSWRT_MCP_BIN%.exe"
    "%USERPROFILE%\.local\bin\asuswrt-mcp.exe"
    "%USERPROFILE%\.local\bin\asuswrt-mcp"
) do (
    if exist %%C (
        "%%~C" %*
        exit /b !errorlevel!
    )
)

>&2 echo asuswrt-mcp was not found.
>&2 echo.
>&2 echo Install it, then reopen Claude Desktop:
>&2 echo   uv tool install "asuswrt[mcp] @ git+https://github.com/gittycat/asuswrt-tools"
>&2 echo.
>&2 echo If it is installed somewhere else, put the full path in the extension's
>&2 echo "Path to asuswrt-mcp" setting (Settings - Extensions - ASUS Router Control).
exit /b 1
