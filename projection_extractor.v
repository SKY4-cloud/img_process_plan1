`timescale 1ns / 1ps

// projection_extractor: X/Y projection + bbox; optional area/aspect gate (plate-like regions).
// USE_Y_BAND=1：列累加仅统计 y_first..y_last 行；State1 仅在该带内扫 y_ram。
// USE_X_BAND=1：列累加仅统计 x_first..x_last 列；State2 仅在该带内扫 x_ram。
// COL_THR 在 XY 带均开时表示「两带交集内」列计数门限，标定可能需重调。
module projection_extractor #(
    parameter IMG_WIDTH   = 720,
    parameter IMG_HEIGHT  = 1160,
    parameter THRESHOLD   = 5,
    parameter X_THRESHOLD = 0,
    // 行投影门限；为 0 时与 THRESHOLD 相同
    parameter Y_THRESHOLD = 0,
    parameter MIN_AREA    = 200,
    parameter MIN_WH_NUM  = 5,
    parameter MIN_WH_DEN  = 2,
    parameter MAX_WH_NUM  = 11,
    parameter MAX_WH_DEN  = 2,
    // 竖直先验带：y_first=(H*TOP_N)/TOP_D，y_last=(H*BOT_N)/BOT_D-1；USE_Y_BAND=0 时等价全图
    parameter USE_Y_BAND      = 1,
    parameter [31:0] Y_BAND_TOP_N = 32'd1,
    parameter [31:0] Y_BAND_TOP_D = 32'd4,
    parameter [31:0] Y_BAND_BOT_N = 32'd3,
    parameter [31:0] Y_BAND_BOT_D = 32'd4,
    // 水平先验带：x_first=(W*LEFT_N)/LEFT_D，x_last=(W*RIGHT_N)/RIGHT_D-1；USE_X_BAND=0 时等价全宽
    parameter USE_X_BAND       = 1,
    parameter [31:0] X_BAND_LEFT_N  = 32'd1,
    parameter [31:0] X_BAND_LEFT_D  = 32'd5,
    parameter [31:0] X_BAND_RIGHT_N = 32'd4,
    parameter [31:0] X_BAND_RIGHT_D = 32'd5,
    // 投影框在边缘常被低估（列/行计数低于阈值、形态学收缩）；外扩后钳位，泛化修复“缺一边字符”
    parameter [11:0] BOX_PAD_XL = 12'd0,
    parameter [11:0] BOX_PAD_XR = 12'd0,
    parameter [11:0] BOX_PAD_YT = 12'd0,
    parameter [11:0] BOX_PAD_YB = 12'd0
)(
    input  wire        clk,
    input  wire        rst_n,

    input  wire        vs_in,
    input  wire        de_in,
    input  wire [7:0]  bin_data,

    output reg  [11:0] out_x_min,
    output reg  [11:0] out_x_max,
    output reg  [11:0] out_y_min,
    output reg  [11:0] out_y_max,
    output reg         box_valid
);

    reg [11:0] x_ram [0:2047];
    reg [11:0] y_ram [0:2047];

    integer i;
    initial begin
        for (i=0; i<2048; i=i+1) begin
            x_ram[i] = 0;
            y_ram[i] = 0;
        end
    end

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

    reg [11:0] row_w_cnt;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            row_w_cnt <= 0;
        end else begin
            if (de_in && bin_data == 8'hFF) begin
                row_w_cnt <= row_w_cnt + 1;
            end else if (de_fall) begin
                y_ram[y_cnt] <= row_w_cnt;
                row_w_cnt <= 0;
            end
        end
    end

    reg [2:0]  state;
    reg [11:0] scan_cnt;
    reg [11:0] tmp_x_min, tmp_x_max;
    reg [11:0] tmp_y_min, tmp_y_max;

    wire [11:0] box_w  = tmp_x_max - tmp_x_min + 1;
    wire [11:0] box_h  = tmp_y_max - tmp_y_min + 1;
    wire [23:0] area   = box_w * box_h;
    localparam [11:0] COL_THR = (X_THRESHOLD > 0) ? X_THRESHOLD[11:0] : THRESHOLD[11:0];
    localparam [11:0] ROW_THR = (Y_THRESHOLD > 0) ? Y_THRESHOLD[11:0] : THRESHOLD[11:0];

    wire        y_band_en = (USE_Y_BAND != 0);
    wire [11:0] y_hi_m1   = IMG_HEIGHT[11:0] - 12'd1;
    wire [31:0] mul_y_top = IMG_HEIGHT * Y_BAND_TOP_N;
    wire [31:0] mul_y_bot = IMG_HEIGHT * Y_BAND_BOT_N;
    wire [11:0] y_first_c = mul_y_top / Y_BAND_TOP_D;
    wire [11:0] y_last_c  = mul_y_bot / Y_BAND_BOT_D - 12'd1;
    wire [11:0] y_first_cl = y_first_c > y_hi_m1 ? y_hi_m1 : y_first_c[11:0];
    wire [11:0] y_last_cl  = y_last_c  > y_hi_m1 ? y_hi_m1 : y_last_c[11:0];
    wire [11:0] y_first    = y_band_en ? y_first_cl : 12'd0;
    wire [11:0] y_last     = y_band_en ? y_last_cl  : y_hi_m1;
    // 带内分数无效（上沿>下沿）时跳过 State1，无 Y 检测
    wire        y_band_ok  = !y_band_en || (y_first_cl <= y_last_cl);

    wire        x_band_en = (USE_X_BAND != 0);
    wire [11:0] w_hi_m1   = IMG_WIDTH[11:0] - 12'd1;
    wire [31:0] mul_x_l   = IMG_WIDTH * X_BAND_LEFT_N;
    wire [31:0] mul_x_r   = IMG_WIDTH * X_BAND_RIGHT_N;
    wire [11:0] x_first_c = mul_x_l / X_BAND_LEFT_D;
    wire [11:0] x_last_c  = mul_x_r / X_BAND_RIGHT_D - 12'd1;
    wire [11:0] x_first_cl = x_first_c > w_hi_m1 ? w_hi_m1 : x_first_c[11:0];
    wire [11:0] x_last_cl  = x_last_c  > w_hi_m1 ? w_hi_m1 : x_last_c[11:0];
    wire [11:0] x_first    = x_band_en ? x_first_cl : 12'd0;
    wire [11:0] x_last     = x_band_en ? x_last_cl  : w_hi_m1;
    wire        x_band_ok   = !x_band_en || (x_first_cl <= x_last_cl);

    wire        det_ok = (tmp_y_min != 12'hFFF) && (tmp_x_min != 12'hFFF);
    wire        aspect_ok = (box_w * MIN_WH_DEN >= box_h * MIN_WH_NUM)
                         && (box_w * MAX_WH_DEN <= box_h * MAX_WH_NUM)
                         && (box_w >= box_h);
    wire        geom_ok   = det_ok && (area >= MIN_AREA) && aspect_ok;

    wire [12:0] pad_xmin_ext = {1'b0, tmp_x_min} - {1'b0, BOX_PAD_XL};
    wire [11:0] pad_xmin     = pad_xmin_ext[12] ? 12'd0 : pad_xmin_ext[11:0];
    wire [12:0] pad_xmax_sum = {1'b0, tmp_x_max} + {1'b0, BOX_PAD_XR};
    wire [11:0] pad_xmax     = (pad_xmax_sum >= IMG_WIDTH) ? (IMG_WIDTH - 12'd1) : pad_xmax_sum[11:0];

    wire [12:0] pad_ymin_ext = {1'b0, tmp_y_min} - {1'b0, BOX_PAD_YT};
    wire [11:0] pad_ymin     = pad_ymin_ext[12] ? 12'd0 : pad_ymin_ext[11:0];
    wire [12:0] pad_ymax_sum = {1'b0, tmp_y_max} + {1'b0, BOX_PAD_YB};
    wire [11:0] pad_ymax     = (pad_ymax_sum >= IMG_HEIGHT) ? (IMG_HEIGHT - 12'd1) : pad_ymax_sum[11:0];

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= 0; scan_cnt <= 0; box_valid <= 0;
            out_x_min <= 0; out_x_max <= 0; out_y_min <= 0; out_y_max <= 0;
        end else begin
            case (state)
                0: begin
                    box_valid <= 0;
                    if (de_in && bin_data == 8'hFF
                        && (y_cnt >= y_first) && (y_cnt <= y_last)
                        && (x_cnt >= x_first) && (x_cnt <= x_last)) begin
                        x_ram[x_cnt] <= x_ram[x_cnt] + 1;
                    end

                    if (vs_rise) begin
                        tmp_y_min <= 12'hFFF; tmp_y_max <= 0;
                        tmp_x_min <= 12'hFFF; tmp_x_max <= 0;
                        if (!y_band_ok) begin
                            state    <= 2;
                            scan_cnt <= x_first;
                        end else begin
                            state    <= 1;
                            scan_cnt <= y_first;
                        end
                    end
                end
                1: begin
                    if (scan_cnt <= y_last) begin
                        if (y_ram[scan_cnt] >= ROW_THR) begin
                            if (tmp_y_min == 12'hFFF) tmp_y_min <= scan_cnt;
                            tmp_y_max <= scan_cnt;
                        end
                        if (scan_cnt == y_last) begin
                            state    <= 2;
                            scan_cnt <= x_first;
                        end else
                            scan_cnt <= scan_cnt + 1;
                    end else begin
                        state    <= 2;
                        scan_cnt <= x_first;
                    end
                end
                2: begin
                    if (!x_band_ok) begin
                        state <= 3; scan_cnt <= 0;
                        // synthesis translate_off
                        $display("[proj] raw X: %0d..%0d  Y: %0d..%0d  w=%0d h=%0d area=%0d",
                                 tmp_x_min, tmp_x_max, tmp_y_min, tmp_y_max,
                                 box_w, box_h, area);
                        $display("[proj] det_ok=%b area_ok=%b aspect_ok=%b => geom_ok=%b",
                                 det_ok, (area >= MIN_AREA), aspect_ok, geom_ok);
                        // synthesis translate_on
                        if (geom_ok) begin
                            out_x_min <= pad_xmin;
                            out_x_max <= pad_xmax;
                            out_y_min <= pad_ymin;
                            out_y_max <= pad_ymax;
                            box_valid <= 1'b1;
                        end
                    end else if (scan_cnt <= x_last) begin
                        if (x_ram[scan_cnt] >= COL_THR) begin
                            if (tmp_x_min == 12'hFFF) tmp_x_min <= scan_cnt;
                            tmp_x_max <= scan_cnt;
                        end
                        if (scan_cnt == x_last) begin
                            state <= 3; scan_cnt <= 0;
                            // synthesis translate_off
                            $display("[proj] raw X: %0d..%0d  Y: %0d..%0d  w=%0d h=%0d area=%0d",
                                     tmp_x_min, tmp_x_max, tmp_y_min, tmp_y_max,
                                     box_w, box_h, area);
                            $display("[proj] det_ok=%b area_ok=%b aspect_ok=%b => geom_ok=%b",
                                     det_ok, (area >= MIN_AREA), aspect_ok, geom_ok);
                            // synthesis translate_on
                            if (geom_ok) begin
                                out_x_min <= pad_xmin;
                                out_x_max <= pad_xmax;
                                out_y_min <= pad_ymin;
                                out_y_max <= pad_ymax;
                                box_valid <= 1'b1;
                            end
                        end else
                            scan_cnt <= scan_cnt + 1;
                    end else begin
                        state <= 3; scan_cnt <= 0;
                        // synthesis translate_off
                        $display("[proj] raw X: %0d..%0d  Y: %0d..%0d  w=%0d h=%0d area=%0d",
                                 tmp_x_min, tmp_x_max, tmp_y_min, tmp_y_max,
                                 box_w, box_h, area);
                        $display("[proj] det_ok=%b area_ok=%b aspect_ok=%b => geom_ok=%b",
                                 det_ok, (area >= MIN_AREA), aspect_ok, geom_ok);
                        // synthesis translate_on
                        if (geom_ok) begin
                            out_x_min <= pad_xmin;
                            out_x_max <= pad_xmax;
                            out_y_min <= pad_ymin;
                            out_y_max <= pad_ymax;
                            box_valid <= 1'b1;
                        end
                    end
                end
                3: begin
                    box_valid <= 0;
                    if (scan_cnt < IMG_WIDTH) begin
                        x_ram[scan_cnt] <= 0;
                        scan_cnt <= scan_cnt + 1;
                    end else begin
                        state <= 0;
                    end
                end
                default: state <= 0;
            endcase
        end
    end
endmodule
