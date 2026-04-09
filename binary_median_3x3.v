`timescale 1ns / 1ps
// 3x3 二值中值滤波：对 0/255 掩膜等价于「≥5 个像素为白则输出白」
// 与 morphology.v 一致，用像素最高位表示二值，延迟 1 拍对齐 vs/de
module binary_median_3x3 (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        matrix_vs,
    input  wire        matrix_de,
    input  wire [7:0]  p11,
    input  wire [7:0]  p12,
    input  wire [7:0]  p13,
    input  wire [7:0]  p21,
    input  wire [7:0]  p22,
    input  wire [7:0]  p23,
    input  wire [7:0]  p31,
    input  wire [7:0]  p32,
    input  wire [7:0]  p33,
    output reg         out_vs,
    output reg         out_de,
    output reg  [7:0]  out_data
);

    wire b11 = p11[7];
    wire b12 = p12[7];
    wire b13 = p13[7];
    wire b21 = p21[7];
    wire b22 = p22[7];
    wire b23 = p23[7];
    wire b31 = p31[7];
    wire b32 = p32[7];
    wire b33 = p33[7];

    wire [3:0] popcnt = b11 + b12 + b13 + b21 + b22 + b23 + b31 + b32 + b33;

    wire majority = (popcnt >= 4'd5);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            out_vs   <= 1'b0;
            out_de   <= 1'b0;
            out_data <= 8'd0;
        end else begin
            out_vs   <= matrix_vs;
            out_de   <= matrix_de;
            out_data <= majority ? 8'd255 : 8'd0;
        end
    end

endmodule
