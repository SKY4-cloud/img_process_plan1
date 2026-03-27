@echo off
setlocal
cd /d "%~dp0"

if not exist "image_in.txt" (
  echo [!] Missing image_in.txt — generate with: python python\img_to_hex.py -i your.bmp -o image_in.txt
  exit /b 1
)

iverilog -g2012 -Wall -o sim.vvp ^
  tb_img_process.v ^
  image_process_wrapper.v ^
  roi_crop_scale.v ^
  projection_extractor.v ^
  osd_draw_box.v ^
  matrix_3x3.v ^
  fifo_line_buf.v ^
  morphology.v ^
  RGB2YCbCr_1.v
if errorlevel 1 exit /b 1

echo Running vvp...
vvp sim.vvp
exit /b %ERRORLEVEL%
