`timescale 1ns / 1ps
// =====================================================================
// 架构师手写：专为 matrix_3x3 匹配的纯净版 FIFO 仿真模型
// 彻底摆脱紫光底层库依赖！
// =====================================================================
module fifo_line_buf #(
    parameter DATA_WIDTH = 8,
    parameter ADDR_WIDTH = 11
)(
    // 写端口
    input  wire                  wr_clk,
    input  wire                  wr_rst,
    input  wire                  wr_en,
    input  wire [DATA_WIDTH-1:0] wr_data,
    output wire                  wr_full,
    output wire                  almost_full,

    // 读端口
    input  wire                  rd_clk,
    input  wire                  rd_rst,
    input  wire                  rd_en,
    output reg  [DATA_WIDTH-1:0] rd_data,
    output wire                  rd_empty,
    output wire                  almost_empty
);
    // 内部存储器
    reg [DATA_WIDTH-1:0] mem [0:(1<<ADDR_WIDTH)-1];
    reg [ADDR_WIDTH:0] wr_ptr;
    reg [ADDR_WIDTH:0] rd_ptr;

    // 1. 写逻辑
    always @(posedge wr_clk or posedge wr_rst) begin
        if (wr_rst) begin
            wr_ptr <= 0;
        end else if (wr_en && !wr_full) begin
            mem[wr_ptr[ADDR_WIDTH-1:0]] <= wr_data;
            wr_ptr <= wr_ptr + 1;
        end
    end

    // 2. 读逻辑
    always @(posedge rd_clk or posedge rd_rst) begin
        if (rd_rst) begin
            rd_ptr  <= 0;
            rd_data <= 0;
        end else if (rd_en && !rd_empty) begin
            rd_data <= mem[rd_ptr[ADDR_WIDTH-1:0]];
            rd_ptr  <= rd_ptr + 1;
        end
    end

    // 3. 状态标志生成
    assign wr_full  = (wr_ptr[ADDR_WIDTH] != rd_ptr[ADDR_WIDTH]) && 
                      (wr_ptr[ADDR_WIDTH-1:0] == rd_ptr[ADDR_WIDTH-1:0]);
    assign rd_empty = (wr_ptr == rd_ptr);
    
    // matrix_3x3 中未实际使用这两个信号，直接赋 0 防止悬空报错
    assign almost_full  = 1'b0; 
    assign almost_empty = 1'b0; 

endmodule