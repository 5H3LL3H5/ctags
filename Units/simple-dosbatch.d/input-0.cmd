for %%i in (*.exe) do call :strip %%i

:strip
objcopy --only-keep-debug %1 %1.debug
strip %1
objcopy --add-gnu-debuglink=%1.debug %1
goto :eof
