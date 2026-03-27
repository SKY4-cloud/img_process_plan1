`timescale 1ns / 1ps

// =====================================================================
// 模块名称：osd_draw_box (硬件动态画框器)
// 架构师解析：利用上一帧算出的坐标，在当前帧的原始视频流上实时覆盖红色边框
// =====================================================================
module osd_draw_box #(
    parameter LINE_WIDTH  = 3,     // 画框的线条宽度（像素）
    // 默认边框颜色：纯红色 (RGB = 255, 0, 0)
    parameter BOX_COLOR_R = 8'hFF, 
    parameter BOX_COLOR_G = 8'h00,
    parameter BOX_COLOR_B = 8'h00
)(
    input  wire        clk,
    input  wire        rst_n,

    // 1. 原始高清视频流输入 (例如直接来自摄像头)
    input  wire        vs_in,
    input  wire        de_in,
    input  wire [7:0]  r_in,
    input  wire [7:0]  g_in,
    input  wire [7:0]  b_in,

    // 2. 硬件投影器给出的实时坐标 (上帧结果)
    input  wire [11:0] box_x_min,
    input  wire [11:0] box_x_max,
    input  wire [11:0] box_y_min,
    input  wire [11:0] box_y_max,

    // 3. 画好框的视频流输出 (送给 HDMI 显示)
    output reg         vs_out,
    output reg         de_out,
    output reg  [7:0]  r_out,
    output reg  [7:0]  g_out,
    output reg  [7:0]  b_out
);

    // --- 1. 同步生成原始图像的实时坐标 (x_cnt, y_cnt) ---
    reg        de_r;
    reg        vs_r;
    always @(posedge clk) begin
        de_r <= de_in;
        vs_r <= vs_in;
    end
    wire de_fall = de_r & ~de_in;
    wire vs_rise = ~vs_r & vs_in;

    reg [11:0] x_cnt;
    reg [11:0] y_cnt;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            x_cnt <= 0; y_cnt <= 0;
        end else begin
            if (vs_rise) begin
                x_cnt <= 0; y_cnt <= 0;
            end else if (de_in) begin
                x_cnt <= x_cnt + 1;
            end else if (de_fall) begin
                x_cnt <= 0; y_cnt <= y_cnt + 1;
            end
        end
    end

    // --- 2. 锁存坐标 (防止一帧画到一半时，坐标突然跳变导致框被撕裂) ---
    reg [11:0] latch_x_min, latch_x_max;
    reg [11:0] latch_y_min, latch_y_max;
    
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            latch_x_min <= 0; latch_x_max <= 0;
            latch_y_min <= 0; latch_y_max <= 0;
        end else if (de_in && x_cnt == 0 && y_cnt == 0) begin
            // 在每一帧画面的最开头，把探测器给的坐标抓过来锁死
            latch_x_min <= box_x_min;
            latch_x_max <= box_x_max;
            latch_y_min <= box_y_min;
            latch_y_max <= box_y_max;
        end
    end

    // --- 3. 核心画框逻辑 (判断当前像素是否踩在边线上) ---
    wire is_top_edge = (y_cnt >= latch_y_min) && (y_cnt < latch_y_min + LINE_WIDTH) && (x_cnt >= latch_x_min) && (x_cnt <= latch_x_max);
    wire is_bot_edge = (y_cnt <= latch_y_max) && (y_cnt > latch_y_max - LINE_WIDTH) && (x_cnt >= latch_x_min) && (x_cnt <= latch_x_max);
    wire is_lef_edge = (x_cnt >= latch_x_min) && (x_cnt < latch_x_min + LINE_WIDTH) && (y_cnt >= latch_y_min) && (y_cnt <= latch_y_max);
    wire is_rig_edge = (x_cnt <= latch_x_max) && (x_cnt > latch_x_max - LINE_WIDTH) && (y_cnt >= latch_y_min) && (y_cnt <= latch_y_max);

    // 只要踩中任意一条边，就开启“染色”
    wire draw_en = is_top_edge | is_bot_edge | is_lef_edge | is_rig_edge;

    // --- 4. 视频流输出染色 (1 拍延迟对齐) ---
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            vs_out <= 0; de_out <= 0;
            r_out <= 0;  g_out <= 0;  b_out <= 0;
        end else begin
            vs_out <= vs_in;
            de_out <= de_in;
            
            if (de_in) begin
                if (draw_en) begin
                    // 覆盖为边框颜色 (强行染色)
                    r_out <= BOX_COLOR_R;
                    g_out <= BOX_COLOR_G;
                    b_out <= BOX_COLOR_B;
                end else begin
                    // 保持原样透传
                    r_out <= r_in;
                    g_out <= g_in;
                    b_out <= b_in;
                end
            end else begin
                r_out <= 0; g_out <= 0; b_out <= 0;
            end
        end
    end

endmodule