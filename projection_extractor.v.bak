`timescale 1ns / 1ps

// projection_extractor: X/Y projection + bbox; optional area/aspect gate (plate-like regions).
module projection_extractor #(
    parameter IMG_WIDTH  = 640,
    parameter IMG_HEIGHT = 480,
    parameter THRESHOLD  = 5,
    parameter MIN_AREA   = 200,
    parameter MIN_WH_NUM = 5,
    parameter MIN_WH_DEN = 2,
    parameter MAX_WH_NUM = 11,
    parameter MAX_WH_DEN = 2
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
    wire        det_ok = (tmp_y_min != 12'hFFF) && (tmp_x_min != 12'hFFF);
    wire        aspect_ok = (box_w * MIN_WH_DEN >= box_h * MIN_WH_NUM)
                         && (box_w * MAX_WH_DEN <= box_h * MAX_WH_NUM)
                         && (box_w >= box_h);
    wire        geom_ok   = det_ok && (area >= MIN_AREA) && aspect_ok;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= 0; scan_cnt <= 0; box_valid <= 0;
            out_x_min <= 0; out_x_max <= 0; out_y_min <= 0; out_y_max <= 0;
        end else begin
            case (state)
                0: begin
                    box_valid <= 0;
                    if (de_in && bin_data == 8'hFF) begin
                        x_ram[x_cnt] <= x_ram[x_cnt] + 1;
                    end

                    if (vs_rise) begin
                        state <= 1; scan_cnt <= 0;
                        tmp_y_min <= 12'hFFF; tmp_y_max <= 0;
                        tmp_x_min <= 12'hFFF; tmp_x_max <= 0;
                    end
                end
                1: begin
                    if (scan_cnt < IMG_HEIGHT) begin
                        if (y_ram[scan_cnt] >= THRESHOLD) begin
                            if (tmp_y_min == 12'hFFF) tmp_y_min <= scan_cnt;
                            tmp_y_max <= scan_cnt;
                        end
                        scan_cnt <= scan_cnt + 1;
                    end else begin
                        state <= 2; scan_cnt <= 0;
                    end
                end
                2: begin
                    if (scan_cnt < IMG_WIDTH) begin
                        if (x_ram[scan_cnt] >= THRESHOLD) begin
                            if (tmp_x_min == 12'hFFF) tmp_x_min <= scan_cnt;
                            tmp_x_max <= scan_cnt;
                        end
                        scan_cnt <= scan_cnt + 1;
                    end else begin
                        state <= 3; scan_cnt <= 0;
                        if (geom_ok) begin
                            out_x_min <= tmp_x_min;
                            out_x_max <= tmp_x_max;
                            out_y_min <= tmp_y_min;
                            out_y_max <= tmp_y_max;
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
