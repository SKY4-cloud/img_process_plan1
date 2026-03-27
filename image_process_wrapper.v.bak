`timescale 1ns / 1ps

module image_process_wrapper #(
    parameter IMG_WIDTH  = 640,
    parameter IMG_HEIGHT = 480,
    parameter CB_MIN     = 8'd150,
    parameter CB_MAX     = 8'd255,
    parameter CR_MIN     = 8'd86,
    parameter CR_MAX     = 8'd124,
    parameter Y_MIN      = 8'd30,
    parameter Y_MAX      = 8'd100,
    parameter PROJ_MIN_AREA   = 200,
    parameter PROJ_MIN_WH_N   = 5,
    parameter PROJ_MIN_WH_D   = 2,
    parameter PROJ_MAX_WH_N   = 11,
    parameter PROJ_MAX_WH_D   = 2,
    parameter ROI_OUT_W  = 64,
    parameter ROI_OUT_H  = 32,
    parameter MAX_ROI_W  = 640,
    parameter MAX_ROI_H  = 240
)(
    input  wire        clk,
    input  wire        rst_n,

    input  wire        vs_in,
    input  wire        de_in,
    input  wire [7:0]  r_in,
    input  wire [7:0]  g_in,
    input  wire [7:0]  b_in,

    output wire        post_vs,
    output wire        post_de,
    output wire [7:0]  post_data,

    output wire        osd_vs,
    output wire        osd_de,
    output wire [23:0] osd_rgb,

    output wire        roi_vs,
    output wire        roi_de,
    output wire [23:0] roi_rgb,
    output wire        roi_frame_done
);

    wire        y_vs;
    wire        y_hs;
    wire        y_de;
    wire [7:0]  y_data;
    wire [7:0]  cb_data;
    wire [7:0]  cr_data;

    RGB2YCbCr_1 RGB2YCbCr_inst (
        .clk        (clk),
        .rst_n      (rst_n),
        .vsync_in   (vs_in),
        .hsync_in   (de_in),
        .de_in      (de_in),
        .red        (r_in[7:3]),
        .green      (g_in[7:2]),
        .blue       (b_in[7:3]),
        .vsync_out  (y_vs),
        .hsync_out  (y_hs),
        .de_out     (y_de),
        .y          (y_data),
        .cb         (cb_data),
        .cr         (cr_data)
    );

    reg         cb_bin_vs;
    reg         cb_bin_de;
    reg  [7:0]  cb_bin_data;

    wire blue_fg = (cb_data >= CB_MIN) && (cb_data <= CB_MAX)
                && (cr_data >= CR_MIN) && (cr_data <= CR_MAX)
                && (y_data  >= Y_MIN)  && (y_data  <= Y_MAX);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cb_bin_vs   <= 0;
            cb_bin_de   <= 0;
            cb_bin_data <= 8'd0;
        end else begin
            cb_bin_vs   <= y_vs;
            cb_bin_de   <= y_de;
            cb_bin_data <= blue_fg ? 8'd255 : 8'd0;
        end
    end

    wire        matrix1_de;
    wire [7:0]  m1_11, m1_12, m1_13;
    wire [7:0]  m1_21, m1_22, m1_23;
    wire [7:0]  m1_31, m1_32, m1_33;

    matrix_3x3 #(
        .IMG_WIDTH  ( IMG_WIDTH  ),
        .IMG_HEIGHT ( IMG_HEIGHT )
    ) u_matrix_3x3_inst1 (
        .video_clk  ( clk ),
        .rst_n      ( rst_n ),
        .video_vs   ( cb_bin_vs ),
        .video_de   ( cb_bin_de ),
        .video_data ( cb_bin_data ),
        .matrix_de  ( matrix1_de ),
        .matrix11(m1_11), .matrix12(m1_12), .matrix13(m1_13),
        .matrix21(m1_21), .matrix22(m1_22), .matrix23(m1_23),
        .matrix31(m1_31), .matrix32(m1_32), .matrix33(m1_33)
    );

    wire        morph1_vs;
    wire        morph1_de;
    wire [7:0]  morph1_dilate;

    morphology u_morphology_dilate (
        .clk         ( clk ),
        .rst_n       ( rst_n ),
        .matrix_vs   ( cb_bin_vs ),
        .matrix_de   ( matrix1_de ),
        .p11(m1_11), .p12(m1_12), .p13(m1_13),
        .p21(m1_21), .p22(m1_22), .p23(m1_23),
        .p31(m1_31), .p32(m1_32), .p33(m1_33),
        .out_vs      ( morph1_vs ),
        .out_de      ( morph1_de ),
        .dilate_data ( morph1_dilate ),
        .erode_data  ( )
    );

    wire        matrix2_de;
    wire [7:0]  m2_11, m2_12, m2_13;
    wire [7:0]  m2_21, m2_22, m2_23;
    wire [7:0]  m2_31, m2_32, m2_33;

    matrix_3x3 #(
        .IMG_WIDTH  ( IMG_WIDTH  ),
        .IMG_HEIGHT ( IMG_HEIGHT )
    ) u_matrix_3x3_inst2 (
        .video_clk  ( clk ),
        .rst_n      ( rst_n ),
        .video_vs   ( morph1_vs ),
        .video_de   ( morph1_de ),
        .video_data ( morph1_dilate),
        .matrix_de  ( matrix2_de ),
        .matrix11(m2_11), .matrix12(m2_12), .matrix13(m2_13),
        .matrix21(m2_21), .matrix22(m2_22), .matrix23(m2_23),
        .matrix31(m2_31), .matrix32(m2_32), .matrix33(m2_33)
    );

    wire [7:0]  morph2_erode;

    morphology u_morphology_erode (
        .clk         ( clk ),
        .rst_n       ( rst_n ),
        .matrix_vs   ( morph1_vs ),
        .matrix_de   ( matrix2_de ),
        .p11(m2_11), .p12(m2_12), .p13(m2_13),
        .p21(m2_21), .p22(m2_22), .p23(m2_23),
        .p31(m2_31), .p32(m2_32), .p33(m2_33),
        .out_vs      ( post_vs ),
        .out_de      ( post_de ),
        .dilate_data ( ),
        .erode_data  ( morph2_erode )
    );

    assign post_data = morph2_erode;

    wire [11:0] box_x_min, box_x_max, box_y_min, box_y_max;
    wire        box_valid;

    projection_extractor #(
        .IMG_WIDTH  ( IMG_WIDTH  ),
        .IMG_HEIGHT ( IMG_HEIGHT ),
        .THRESHOLD  ( 5 ),
        .MIN_AREA   ( PROJ_MIN_AREA ),
        .MIN_WH_NUM ( PROJ_MIN_WH_N ),
        .MIN_WH_DEN ( PROJ_MIN_WH_D ),
        .MAX_WH_NUM ( PROJ_MAX_WH_N ),
        .MAX_WH_DEN ( PROJ_MAX_WH_D )
    ) u_projection (
        .clk        ( clk ),
        .rst_n      ( rst_n ),
        .vs_in      ( post_vs ),
        .de_in      ( post_de ),
        .bin_data   ( post_data ),
        .out_x_min  ( box_x_min ),
        .out_x_max  ( box_x_max ),
        .out_y_min  ( box_y_min ),
        .out_y_max  ( box_y_max ),
        .box_valid  ( box_valid )
    );

// synthesis translate_off
    always @(posedge clk) begin
        if (box_valid) begin
            $display("\n========================================");
            $display(" [Projection] Box (gated) X: %0d -> %0d  Y: %0d -> %0d",
                     box_x_min, box_x_max, box_y_min, box_y_max);
            $display("========================================\n");
        end
    end
// synthesis translate_on

    wire [7:0] osd_r, osd_g, osd_b;

    osd_draw_box #(
        .LINE_WIDTH ( 2 )
    ) u_osd_draw_box (
        .clk         ( clk ),
        .rst_n       ( rst_n ),
        .vs_in       ( vs_in ),
        .de_in       ( de_in ),
        .r_in        ( r_in ),
        .g_in        ( g_in ),
        .b_in        ( b_in ),
        .box_x_min   ( box_x_min ),
        .box_x_max   ( box_x_max ),
        .box_y_min   ( box_y_min ),
        .box_y_max   ( box_y_max ),
        .vs_out      ( osd_vs ),
        .de_out      ( osd_de ),
        .r_out       ( osd_r ),
        .g_out       ( osd_g ),
        .b_out       ( osd_b )
    );

    assign osd_rgb = {osd_r, osd_g, osd_b};

    roi_crop_scale #(
        .IMG_WIDTH  ( IMG_WIDTH  ),
        .IMG_HEIGHT ( IMG_HEIGHT ),
        .OUT_W      ( ROI_OUT_W ),
        .OUT_H      ( ROI_OUT_H ),
        .MAX_ROI_W  ( MAX_ROI_W ),
        .MAX_ROI_H  ( MAX_ROI_H )
    ) u_roi (
        .clk            ( clk ),
        .rst_n          ( rst_n ),
        .vs_in          ( vs_in ),
        .de_in          ( de_in ),
        .r_in           ( r_in ),
        .g_in           ( g_in ),
        .b_in           ( b_in ),
        .box_x_min      ( box_x_min ),
        .box_x_max      ( box_x_max ),
        .box_y_min      ( box_y_min ),
        .box_y_max      ( box_y_max ),
        .roi_vs         ( roi_vs ),
        .roi_de         ( roi_de ),
        .roi_rgb        ( roi_rgb ),
        .roi_frame_done ( roi_frame_done )
    );

endmodule
