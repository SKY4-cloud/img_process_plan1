`timescale 1ns / 1ps

module tb_img_process();

parameter IMG_WIDTH  = 720;
parameter IMG_HEIGHT = 1160;
parameter PIXEL_NUM  = IMG_WIDTH * IMG_HEIGHT;

// 须与 roi_hex_to_img.py --width/--height 及 image_process_wrapper ROI_OUT_* 一致
parameter ROI_OUT_W  = 128;
parameter ROI_OUT_H  = 64;
parameter ROI_PIXELS = ROI_OUT_W * ROI_OUT_H;

parameter SIM_FRAMES = 5;
// post 侧：negedge out_vsync 后 frame_cnt 才 +1。若 dump 用 frame_cnt==SIM_FRAMES-1，则落笔的是
// 「最后一帧」像素；而 [proj] 在下一帧 vs 上升后扫描的 y_ram 来自「上一帧」。
// 故与 [proj] 对齐应 dump frame_cnt==SIM_FRAMES-2（SIM_FRAMES>=2），否则会出现行统计与 [proj] 不一致。
localparam DUMP_POST_FRC = (SIM_FRAMES >= 2) ? (SIM_FRAMES - 2) : 0;
// 同一次仿真内将 post 各场（有效像素期间 frame_cnt=0..SIM_FRAMES-1）写入 image_out_f0..fN，便于对比。
localparam DUMP_SPLIT_POST = 1;

parameter H_SYNC  = 10;
parameter H_BACK  = 10;
parameter H_DISP  = IMG_WIDTH;
parameter H_FRONT = 10;
parameter H_TOTAL = H_SYNC + H_BACK + H_DISP + H_FRONT;

parameter V_SYNC  = 2;
parameter V_BACK  = 97;
parameter V_DISP  = IMG_HEIGHT;
parameter V_FRONT = 2;
parameter V_TOTAL = V_SYNC + V_BACK + V_DISP + V_FRONT;

reg         clk;
reg         rst_n;

wire        cam_hsync;
wire        cam_vsync;

wire        out_vsync;
wire        out_de;
wire [7:0]  out_data;

wire        out_osd_vs;
wire        out_osd_de;
wire [23:0] out_osd_rgb;

wire        roi_vs;
wire        roi_de;
wire [23:0] roi_rgb;
wire        roi_done;

reg [11:0]  h_cnt;
reg [11:0]  v_cnt;

reg [23:0]  img_mem [0:PIXEL_NUM-1];

integer     file_out;
integer     file_out_f0;
integer     file_out_f1;
integer     file_out_f2;
integer     file_out_f3;
integer     file_out_f4;

initial begin
    clk = 0;
    forever #10 clk = ~clk;
end

initial begin
    rst_n = 0;
    #100;
    rst_n = 1;
end

initial begin
    $readmemh("image_in.txt", img_mem);

    file_out = $fopen("image_out.txt", "w");
    if (!file_out) begin
        $display("[!] ERROR: Cannot create image_out.txt");
        $stop;
    end
    if (DUMP_SPLIT_POST) begin
        file_out_f0 = $fopen("image_out_f0.txt", "w");
        file_out_f1 = $fopen("image_out_f1.txt", "w");
        file_out_f2 = $fopen("image_out_f2.txt", "w");
        file_out_f3 = $fopen("image_out_f3.txt", "w");
        file_out_f4 = $fopen("image_out_f4.txt", "w");
        if (!file_out_f0 || !file_out_f1 || !file_out_f2 || !file_out_f3 || !file_out_f4) begin
            $display("[!] ERROR: Cannot create image_out_f0..f4.txt");
            $stop;
        end
    end
end

wire de_comb = ((h_cnt >= H_SYNC + H_BACK) && (h_cnt < H_SYNC + H_BACK + H_DISP) &&
                (v_cnt >= V_SYNC + V_BACK) && (v_cnt < V_SYNC + V_BACK + V_DISP));

// 索引与 h_cnt/v_cnt 一致（替代 pixel_cnt，避免与光栅隐含不同步）。
wire [31:0] pix_idx = de_comb
    ? ({20'd0, v_cnt - (V_SYNC + V_BACK)} * IMG_WIDTH + {20'd0, h_cnt - (H_SYNC + H_BACK)})
    : 32'd0;

wire [23:0] cam_data_drv = de_comb ? img_mem[pix_idx] : 24'd0;

// vs 必须组合自 v_cnt，与 de_comb 同源；用 always NBA 寄存 vs 会导致 vs 与 de 差拍 → y_cnt 与像素流错位
assign cam_hsync = (h_cnt < H_SYNC) ? 1'b1 : 1'b0;
assign cam_vsync = (v_cnt < V_SYNC) ? 1'b1 : 1'b0;

always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        h_cnt <= 0;
        v_cnt <= 0;
    end else begin
        if (h_cnt == H_TOTAL - 1) begin
            h_cnt <= 0;
            if (v_cnt == V_TOTAL - 1)
                v_cnt <= 0;
            else
                v_cnt <= v_cnt + 1;
        end else begin
            h_cnt <= h_cnt + 1;
        end
    end
end

image_process_wrapper #(
    .IMG_WIDTH      ( IMG_WIDTH  ),
    .IMG_HEIGHT     ( IMG_HEIGHT ),
    .PROJ_MIN_AREA   ( 5437 ),
    .PROJ_THRESHOLD  ( 80 ),
    .PROJ_X_THRESHOLD( 15 ),
    .PROJ_Y_THRESHOLD( 15 ),
    .PROJ_MAX_WH_N   ( 24 ),
    .PROJ_MAX_WH_D   ( 2 ),
    .ROI_OUT_W      ( ROI_OUT_W ),
    .ROI_OUT_H      ( ROI_OUT_H )
) u_image_process_wrapper (
    .clk        ( clk ),
    .rst_n      ( rst_n ),

    .vs_in      ( cam_vsync ),
    .de_in      ( de_comb ),
    .r_in       ( cam_data_drv[23:16] ),
    .g_in       ( cam_data_drv[15:8]  ),
    .b_in       ( cam_data_drv[7:0]   ),

    .post_vs   ( out_vsync ),
    .post_de   ( out_de ),
    .post_data ( out_data ),

    .osd_vs    ( out_osd_vs ),
    .osd_de    ( out_osd_de ),
    .osd_rgb   ( out_osd_rgb ),

    .roi_vs         ( roi_vs ),
    .roi_de         ( roi_de ),
    .roi_rgb        ( roi_rgb ),
    .roi_frame_done ( roi_done )
);

// synthesis translate_off
wire [11:0] mon_vx = u_image_process_wrapper.u_video_xy.x_cnt;
wire [11:0] mon_vy = u_image_process_wrapper.u_video_xy.y_cnt;
wire [11:0] exp_x  = de_comb ? (h_cnt - (H_SYNC + H_BACK)) : 12'd0;
wire [11:0] exp_y  = de_comb ? (v_cnt - (V_SYNC + V_BACK)) : 12'd0;
integer xy_err_cnt;
initial xy_err_cnt = 0;
always @(posedge clk) begin
    if (rst_n && de_comb) begin
        if ((mon_vx !== exp_x) || (mon_vy !== exp_y)) begin
            if (xy_err_cnt < 8) begin
                $display("[tb] video_xy mismatch @%t exp=(%0d,%0d) mon=(%0d,%0d) h=%0d v=%0d",
                         $time, exp_x, exp_y, mon_vx, mon_vy, h_cnt, v_cnt);
                xy_err_cnt <= xy_err_cnt + 1;
            end
        end
    end
end
// synthesis translate_on

reg [11:0] frame_cnt = 0;
always @(negedge out_vsync) begin
    if (!rst_n) begin
        frame_cnt <= 0;
    end else begin
        if (rst_n) begin
            $display("[*] Post frame ended: frame_cnt=%0d (next will be %0d) | %0d / %0d @ %t",
                     frame_cnt, frame_cnt + 1, frame_cnt + 1, SIM_FRAMES, $time);
        end
        if (frame_cnt == SIM_FRAMES - 1) begin
            $display("[+] Simulation finished: %0d frames processed.", SIM_FRAMES);
            // 最后一场 ROI 在 last_px 后才排空；cnt==SIM_FRAMES 时 drain 可能紧贴下一帧 vs，勿过早 fclose
            repeat (2 * ROI_PIXELS + 8192) @(posedge clk);
            if (DUMP_SPLIT_POST) begin
                $fclose(file_out_f0);
                $fclose(file_out_f1);
                $fclose(file_out_f2);
                $fclose(file_out_f3);
                $fclose(file_out_f4);
                $display("[+] Post dump: image_out_f0..f4.txt (场1..5, frame_cnt=0..4); image_out.txt = proj对齐场 (frame_cnt=%0d)",
                         DUMP_POST_FRC);
            end
            $fclose(file_out);
            $fclose(rgb_file);
            $fclose(roi_file);
            #100;
            $stop;
        end
        frame_cnt <= frame_cnt + 1;
    end
end

always @(posedge clk) begin
    if (out_de) begin
        if (DUMP_SPLIT_POST) begin
            if (frame_cnt == 0)
                $fwrite(file_out_f0, "%02x\n", out_data);
            if (frame_cnt == 1)
                $fwrite(file_out_f1, "%02x\n", out_data);
            if (frame_cnt == 2)
                $fwrite(file_out_f2, "%02x\n", out_data);
            if (frame_cnt == 3)
                $fwrite(file_out_f3, "%02x\n", out_data);
            if (frame_cnt == 4)
                $fwrite(file_out_f4, "%02x\n", out_data);
        end
        if (frame_cnt == DUMP_POST_FRC)
            $fwrite(file_out, "%02x\n", out_data);
    end
end

integer rgb_file;
integer roi_file;

initial begin
    rgb_file = $fopen("image_out_rgb.txt", "w");
    if (!rgb_file) begin
        $display("[!] ERROR: Cannot create image_out_rgb.txt");
        $stop;
    end
    roi_file = $fopen("image_out_roi.txt", "w");
    if (!roi_file) begin
        $display("[!] ERROR: Cannot create image_out_roi.txt");
        $stop;
    end
end

// SIM_FRAMES 可 >15；须与 dump 条件同宽
// osd_frame_cnt：与 out_osd_vs 同步（在 clk 上检测上升沿）。最后一帧有效画面期间 cnt==SIM_FRAMES-1。
// ROI：一场的 drain 在 last_px 启动，可持续 8192 clk，而 out_osd_vs 约在 V_FRONT*H_TOTAL 后到来，故 drain 常跨 osd vs。
// 若在 vs 上直接 roi_cap_px=ROI_PIXELS，会与「上一场尚未结束的 drain」同一串 roi_de 拼在一起，文件首像素约偏移 ~1510（与 golden 不符）。
// 做法：在 cnt==SIM_FRAMES-2 的那次 out_osd_vs 仅置 arm_wait_roi_vs；跳过直至下一次 roi_vs（新 drain 的 d_idx==0）再把 roi_cap_px 置 ROI_PIXELS，保证 8192 行来自同一场 drain。
reg [7:0] osd_frame_cnt;
reg       osd_vs_d;
reg       roi_vs_d;
reg       arm_wait_roi_vs;
integer   roi_cap_px;

always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        osd_frame_cnt     <= 8'd0;
        osd_vs_d          <= 1'b0;
        roi_vs_d          <= 1'b0;
        arm_wait_roi_vs   = 1'b0;
        roi_cap_px        = 0;
    end else begin
        osd_vs_d <= out_osd_vs;
        roi_vs_d <= roi_vs;

        // 先于 out_osd_vs 处理：若 vs 与 roi_vs 同周期，应先消费旧 arm 再本周期 arm（阻塞赋值避免与 vs 竞态）
        if (roi_vs && !roi_vs_d && arm_wait_roi_vs) begin
            roi_cap_px      = ROI_PIXELS;
            arm_wait_roi_vs = 1'b0;
        end

        if (out_osd_vs && !osd_vs_d) begin
            if (osd_frame_cnt == SIM_FRAMES - 2)
                arm_wait_roi_vs = 1'b1;
            osd_frame_cnt <= osd_frame_cnt + 1;
        end

        // 3) 写出 drain 像素（arm 之后、roi_vs 之前 roi_cap_px==0，自然丢弃跨 vs 的 drain 尾部）
        if (roi_cap_px > 0 && roi_de) begin
            #0 $fwrite(roi_file, "%02x%02x%02x\n",
                       roi_rgb[23:16], roi_rgb[15:8], roi_rgb[7:0]);
            roi_cap_px = roi_cap_px - 1;
        end
    end
end

wire osd_rgb_dump_sel = (osd_frame_cnt == SIM_FRAMES - 1);

always @(posedge clk) begin
    if (out_osd_de && osd_rgb_dump_sel) begin
        $fwrite(rgb_file, "%02x%02x%02x\n",
                out_osd_rgb[23:16], out_osd_rgb[15:8], out_osd_rgb[7:0]);
    end
end

endmodule
