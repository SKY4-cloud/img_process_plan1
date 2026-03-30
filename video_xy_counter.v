`timescale 1ns / 1ps
// 与相机 vs/de 同步的像素坐标 (x_cnt,y_cnt)；OSD 与 ROI 共用同一实例，保证与红框几何一致。

module video_xy_counter (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        vs_in,
    input  wire        de_in,
    output reg  [11:0] x_cnt,
    output reg  [11:0] y_cnt
);

    reg de_r, vs_r;
    always @(posedge clk) begin
        de_r <= de_in;
        vs_r <= vs_in;
    end
    wire de_fall = de_r & ~de_in;
    wire vs_rise = ~vs_r & vs_in;

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

endmodule
