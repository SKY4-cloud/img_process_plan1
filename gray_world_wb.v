`timescale 1ns / 1ps

// 灰世界白平衡：整帧统计 R/G/B 均值，使三者趋近同一灰均值；增益 Q8（256=1.0），应用于乘法后 >>8。
// 在 vsync 下降沿锁存上一帧 sum、更新增益（ENABLE=1）、并清零累加器（与 ENABLE 无关，避免累加溢出）。
// 输出相对输入 1clk 对齐延迟（vs_out/de_out 与 r/g/b_out 同步）。
module gray_world_wb #(
    parameter IMG_WIDTH  = 720,
    parameter IMG_HEIGHT = 1160,
    parameter ENABLE     = 1,
    parameter [9:0] GAIN_MIN = 10'd128,
    parameter [9:0] GAIN_MAX = 10'd512
)(
    input  wire        clk,
    input  wire        rst_n,

    input  wire        vs_in,
    input  wire        de_in,
    input  wire [7:0]  r_in,
    input  wire [7:0]  g_in,
    input  wire [7:0]  b_in,

    output reg         vs_out,
    output reg         de_out,
    output reg  [7:0]  r_out,
    output reg  [7:0]  g_out,
    output reg  [7:0]  b_out
);

    localparam integer PIX_TOTAL = IMG_WIDTH * IMG_HEIGHT;

    reg        vs_d;
    wire       vs_negedge = vs_d & ~vs_in;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            vs_d <= 1'b0;
        else
            vs_d <= vs_in;
    end

    reg [31:0] sum_r, sum_g, sum_b;
    reg [15:0] gain_r, gain_g, gain_b;

    function automatic [15:0] clamp_gain(input [31:0] raw);
        begin
            if (raw < {22'd0, GAIN_MIN})
                clamp_gain = {22'd0, GAIN_MIN};
            else if (raw > {22'd0, GAIN_MAX})
                clamp_gain = {22'd0, GAIN_MAX};
            else
                clamp_gain = raw[15:0];
        end
    endfunction

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sum_r   <= 32'd0;
            sum_g   <= 32'd0;
            sum_b   <= 32'd0;
            gain_r  <= 16'd256;
            gain_g  <= 16'd256;
            gain_b  <= 16'd256;
        end else if (vs_negedge) begin
            if (ENABLE && PIX_TOTAL > 0) begin
                integer mr, mg, mb, mavg;
                integer gr, gg, gb;
                mr = sum_r / PIX_TOTAL;
                mg = sum_g / PIX_TOTAL;
                mb = sum_b / PIX_TOTAL;
                mavg = (mr + mg + mb) / 3;
                if (mr > 0)
                    gr = (mavg * 256) / mr;
                else
                    gr = 256;
                if (mg > 0)
                    gg = (mavg * 256) / mg;
                else
                    gg = 256;
                if (mb > 0)
                    gb = (mavg * 256) / mb;
                else
                    gb = 256;
                gain_r <= clamp_gain(gr);
                gain_g <= clamp_gain(gg);
                gain_b <= clamp_gain(gb);
            end
            sum_r <= 32'd0;
            sum_g <= 32'd0;
            sum_b <= 32'd0;
        end else if (de_in) begin
            sum_r <= sum_r + {24'd0, r_in};
            sum_g <= sum_g + {24'd0, g_in};
            sum_b <= sum_b + {24'd0, b_in};
        end
    end

    wire [23:0] pr = r_in * gain_r;
    wire [23:0] pg = g_in * gain_g;
    wire [23:0] pb = b_in * gain_b;
    wire [9:0]  rr = pr[23:8];
    wire [9:0]  rg = pg[23:8];
    wire [9:0]  rb = pb[23:8];
    wire [7:0]  r_clip = rr > 10'd255 ? 8'd255 : rr[7:0];
    wire [7:0]  g_clip = rg > 10'd255 ? 8'd255 : rg[7:0];
    wire [7:0]  b_clip = rb > 10'd255 ? 8'd255 : rb[7:0];

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            vs_out <= 1'b0;
            de_out <= 1'b0;
            r_out  <= 8'd0;
            g_out  <= 8'd0;
            b_out  <= 8'd0;
        end else begin
            vs_out <= vs_in;
            de_out <= de_in;
            if (!ENABLE) begin
                r_out <= r_in;
                g_out <= g_in;
                b_out <= b_in;
            end else begin
                r_out <= r_clip;
                g_out <= g_clip;
                b_out <= b_clip;
            end
        end
    end

endmodule
