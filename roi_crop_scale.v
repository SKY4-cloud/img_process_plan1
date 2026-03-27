`timescale 1ns / 1ps
// Nearest-neighbor: capture ROI to BRAM, stream OUT_W x OUT_H. Box latched at (0,0) active pixel.
// Writes disabled while draining. TB: V_BACK * H_TOTAL + ... >= OUT_W*OUT_H + margin.

module roi_crop_scale #(
    parameter IMG_WIDTH   = 640,
    parameter IMG_HEIGHT  = 480,
    parameter OUT_W       = 64,
    parameter OUT_H       = 32,
    parameter MAX_ROI_W   = 640,
    parameter MAX_ROI_H   = 240
)(
    input  wire        clk,
    input  wire        rst_n,

    input  wire        vs_in,
    input  wire        de_in,
    input  wire [7:0]  r_in,
    input  wire [7:0]  g_in,
    input  wire [7:0]  b_in,

    input  wire [11:0] box_x_min,
    input  wire [11:0] box_x_max,
    input  wire [11:0] box_y_min,
    input  wire [11:0] box_y_max,

    output reg         roi_vs,
    output reg         roi_de,
    output reg  [23:0] roi_rgb,

    output reg         roi_frame_done
);

    reg        de_r, vs_r;
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
            x_cnt <= 0;
            y_cnt <= 0;
        end else begin
            if (vs_rise) begin
                x_cnt <= 0;
                y_cnt <= 0;
            end else if (de_in) begin
                x_cnt <= x_cnt + 1;
            end else if (de_fall) begin
                x_cnt <= 0;
                y_cnt <= y_cnt + 1;
            end
        end
    end

    reg [11:0] lat_x_min, lat_x_max, lat_y_min, lat_y_max;
    reg        lat_valid;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            lat_x_min <= 0;
            lat_x_max <= 0;
            lat_y_min <= 0;
            lat_y_max <= 0;
            lat_valid <= 0;
        end else if (de_in && x_cnt == 0 && y_cnt == 0) begin
            lat_x_min <= box_x_min;
            lat_x_max <= box_x_max;
            lat_y_min <= box_y_min;
            lat_y_max <= box_y_max;
            lat_valid <= (box_y_min != 12'hFFF) && (box_x_min != 12'hFFF)
                       && (box_x_max >= box_x_min) && (box_y_max >= box_y_min);
        end
    end

    wire [11:0] bw  = lat_x_max - lat_x_min + 1;
    wire [11:0] bh  = lat_y_max - lat_y_min + 1;
    wire [11:0] ws0 = (bw > MAX_ROI_W) ? MAX_ROI_W[11:0] : bw;
    wire [11:0] hs0 = (bh > MAX_ROI_H) ? MAX_ROI_H[11:0] : bh;

    localparam integer ROI_MEM_DEPTH = MAX_ROI_W * MAX_ROI_H;
    reg [23:0] roi_mem [0:ROI_MEM_DEPTH-1];

    integer ii;
    initial begin
        for (ii = 0; ii < ROI_MEM_DEPTH; ii = ii + 1)
            roi_mem[ii] = 24'd0;
    end

    reg draining;
    wire in_box = lat_valid && de_in && !draining
        && (x_cnt >= lat_x_min) && (x_cnt <= lat_x_max)
        && (y_cnt >= lat_y_min) && (y_cnt <= lat_y_max);

    wire [11:0] rx = x_cnt - lat_x_min;
    wire [11:0] ry = y_cnt - lat_y_min;
    wire [31:0] wr_addr = {20'd0, ry} * MAX_ROI_W + {20'd0, rx};

    always @(posedge clk) begin
        if (in_box && (rx < MAX_ROI_W) && (ry < MAX_ROI_H) && (wr_addr < ROI_MEM_DEPTH))
            roi_mem[wr_addr] <= {r_in, g_in, b_in};
    end

    wire last_px = de_in && (x_cnt == IMG_WIDTH - 1) && (y_cnt == IMG_HEIGHT - 1);

    localparam [31:0] OUT_LAST = OUT_W * OUT_H - 1;

    reg [31:0] d_idx;
    reg [11:0] ws_r;
    reg [11:0] hs_r;

    wire [31:0] ox32 = d_idx % OUT_W;
    wire [31:0] oy32 = d_idx / OUT_W;
    wire [11:0] ox = ox32[11:0];
    wire [11:0] oy = oy32[11:0];

    wire [11:0] denom_x = (OUT_W > 1) ? (OUT_W[11:0] - 1) : 11'd1;
    wire [11:0] denom_y = (OUT_H > 1) ? (OUT_H[11:0] - 1) : 11'd1;

    wire [11:0] wm1 = (ws_r > 0) ? (ws_r - 1) : 11'd0;
    wire [11:0] hm1 = (hs_r > 0) ? (hs_r - 1) : 11'd0;

    wire [23:0] mul_rx = {12'd0, ox} * {12'd0, wm1};
    wire [23:0] mul_ry = {12'd0, oy} * {12'd0, hm1};
    wire [11:0] src_x = mul_rx / denom_x;
    wire [11:0] src_y = mul_ry / denom_y;

    wire [31:0] rd_addr = {20'd0, src_y} * MAX_ROI_W + {20'd0, src_x};

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            draining   <= 0;
            d_idx      <= 0;
            ws_r       <= 0;
            hs_r       <= 0;
            roi_vs     <= 0;
            roi_de     <= 0;
            roi_rgb    <= 0;
            roi_frame_done <= 0;
        end else begin
            roi_vs  <= 0;
            roi_de  <= 0;
            roi_frame_done <= 0;

            if (!draining && last_px && lat_valid && (ws0 >= 1) && (hs0 >= 1)) begin
                draining <= 1;
                d_idx    <= 0;
                ws_r     <= ws0;
                hs_r     <= hs0;
            end else if (draining) begin
                if (d_idx == 0)
                    roi_vs <= 1'b1;
                roi_de  <= 1'b1;
                roi_rgb <= (rd_addr < ROI_MEM_DEPTH) ? roi_mem[rd_addr] : 24'd0;

                if (d_idx == OUT_LAST) begin
                    draining <= 0;
                    roi_frame_done <= 1'b1;
                end else
                    d_idx <= d_idx + 1;
            end
        end
    end

endmodule
