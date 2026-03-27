`timescale 1ns / 1ps

// =====================================================================
// 模块名称：morphology (形态学滤波器)
// 功能描述：对二值化图像(0或255)进行膨胀或腐蚀操作
// =====================================================================
module morphology (
    input  wire        clk,
    input  wire        rst_n,
    
    // 从第二个 3x3 矩阵输入的信号
    input  wire        matrix_vs,
    input  wire        matrix_de,
    input  wire [7:0]  p11, input wire [7:0] p12, input wire [7:0] p13,
    input  wire [7:0]  p21, input wire [7:0] p22, input wire [7:0] p23,
    input  wire [7:0]  p31, input wire [7:0] p32, input wire [7:0] p33,
    
    // 输出处理后的信号
    output reg         out_vs,
    output reg         out_de,
    output reg  [7:0]  dilate_data, // 膨胀输出 (变粗)
    output reg  [7:0]  erode_data   // 腐蚀输出 (变细)
);

    // 提取每个像素的最高位 (255的最高位是1，0的最高位是0)
    // 这样做可以极大地节省 FPGA 的 LUT 资源
    wire b11 = p11[7]; wire b12 = p12[7]; wire b13 = p13[7];
    wire b21 = p21[7]; wire b22 = p22[7]; wire b23 = p23[7];
    wire b31 = p31[7]; wire b32 = p32[7]; wire b33 = p33[7];

    // =========================================================
    // 核心算法逻辑：
    // =========================================================
    // 【膨胀 Dilation】: 3x3 窗口内，只要有1个白点，中心点就变白 (逻辑或)
    wire dilate_bit = b11 | b12 | b13 | 
                      b21 | b22 | b23 | 
                      b31 | b32 | b33 ;

    // 【腐蚀 Erosion】: 3x3 窗口内，必须全是白点，中心点才保持白 (逻辑与)
    wire erode_bit  = b11 & b12 & b13 & 
                      b21 & b22 & b23 & 
                      b31 & b32 & b33 ;

    // =========================================================
    // 时序打拍与输出
    // =========================================================
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            out_vs      <= 0;
            out_de      <= 0;
            dilate_data <= 8'd0;
            erode_data  <= 8'd0;
        end else begin
            // 信号延迟对齐
            out_vs      <= matrix_vs;
            out_de      <= matrix_de;
            
            // 还原回 8bit 像素值 (1变255，0变0)
            dilate_data <= dilate_bit ? 8'd255 : 8'd0;
            erode_data  <= erode_bit  ? 8'd255 : 8'd0;
        end
    end

endmodule