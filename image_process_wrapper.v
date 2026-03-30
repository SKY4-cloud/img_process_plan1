`timescale 1ns / 1ps

module image_process_wrapper #(
    parameter IMG_WIDTH  = 720,
    parameter IMG_HEIGHT = 1160,
    parameter CB_MIN     = 8'd150,
    parameter CB_MAX     = 8'd255,
    parameter CR_MIN     = 8'd55,
    parameter CR_MAX     = 8'd108,
    parameter Y_MIN      = 8'd15,
    parameter Y_MAX      = 8'd85,
    parameter PROJ_MIN_AREA   = 200,
    parameter PROJ_THRESHOLD  = 80,
    parameter PROJ_X_THRESHOLD = 5,
    parameter PROJ_Y_THRESHOLD = 20,
    parameter PROJ_MIN_WH_N   = 5,
    parameter PROJ_MIN_WH_D   = 2,
    parameter PROJ_MAX_WH_N   = 24,
    parameter PROJ_MAX_WH_D   = 2,
    // 竖直先验：列投影与行扫描仅在 [y_first,y_last]（默认约 H/4..3H/4-1）；0=全图
    parameter PROJ_USE_Y_BAND    = 1,
    parameter [31:0] PROJ_Y_BAND_TOP_N = 32'd1,
    parameter [31:0] PROJ_Y_BAND_TOP_D = 32'd4,
    parameter [31:0] PROJ_Y_BAND_BOT_N = 32'd3,
    parameter [31:0] PROJ_Y_BAND_BOT_D = 32'd4,
    // 水平先验：列累加与 State2 扫描仅在 [x_first,x_last]（默认约 W/5..4W/5-1）；0=全宽
    parameter PROJ_USE_X_BAND     = 1,
    parameter [31:0] PROJ_X_BAND_LEFT_N  = 32'd1,
    parameter [31:0] PROJ_X_BAND_LEFT_D  = 32'd5,
    parameter [31:0] PROJ_X_BAND_RIGHT_N = 32'd4,
    parameter [31:0] PROJ_X_BAND_RIGHT_D = 32'd5,
    // 列投影在首末列易漏计（笔画稀疏/腐蚀）；几何门限仍用未外扩框，仅输出外扩（左多右少，泛化）
    parameter [11:0] PROJ_BOX_PAD_XL = 12'd6,
    parameter [11:0] PROJ_BOX_PAD_XR = 12'd6,
    parameter [11:0] PROJ_BOX_PAD_YT = 12'd2,
    parameter [11:0] PROJ_BOX_PAD_YB = 12'd2,
    parameter ROI_OUT_W  = 128,
    parameter ROI_OUT_H  = 64,
    parameter MAX_ROI_W  = 720,
    parameter MAX_ROI_H  = 580,
    parameter ENABLE_GRAY_WORLD_WB = 1
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

    wire        wb_vs;
    wire        wb_de;
    wire [7:0]  wb_r;
    wire [7:0]  wb_g;
    wire [7:0]  wb_b;

    gray_world_wb #(
        .IMG_WIDTH  ( IMG_WIDTH  ),
        .IMG_HEIGHT ( IMG_HEIGHT ),
        .ENABLE     ( ENABLE_GRAY_WORLD_WB )
    ) u_gray_world_wb (
        .clk    ( clk ),
        .rst_n  ( rst_n ),
        .vs_in  ( vs_in ),
        .de_in  ( de_in ),
        .r_in   ( r_in ),
        .g_in   ( g_in ),
        .b_in   ( b_in ),
        .vs_out ( wb_vs ),
        .de_out ( wb_de ),
        .r_out  ( wb_r ),
        .g_out  ( wb_g ),
        .b_out  ( wb_b )
    );

    RGB2YCbCr_1 RGB2YCbCr_inst (
        .clk        (clk),
        .rst_n      (rst_n),
        .vsync_in   (wb_vs),
        .hsync_in   (wb_de),
        .de_in      (wb_de),
        .red        (wb_r[7:3]),
        .green      (wb_g[7:2]),
        .blue       (wb_b[7:3]),
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
        .THRESHOLD   ( PROJ_THRESHOLD ),
        .X_THRESHOLD ( PROJ_X_THRESHOLD ),
        .Y_THRESHOLD ( PROJ_Y_THRESHOLD ),
        .MIN_AREA    ( PROJ_MIN_AREA ),
        .MIN_WH_NUM ( PROJ_MIN_WH_N ),
        .MIN_WH_DEN ( PROJ_MIN_WH_D ),
        .MAX_WH_NUM ( PROJ_MAX_WH_N ),
        .MAX_WH_DEN ( PROJ_MAX_WH_D ),
        .BOX_PAD_XL ( PROJ_BOX_PAD_XL ),
        .BOX_PAD_XR ( PROJ_BOX_PAD_XR ),
        .BOX_PAD_YT ( PROJ_BOX_PAD_YT ),
        .BOX_PAD_YB ( PROJ_BOX_PAD_YB ),
        .USE_Y_BAND      ( PROJ_USE_Y_BAND ),
        .Y_BAND_TOP_N     ( PROJ_Y_BAND_TOP_N ),
        .Y_BAND_TOP_D     ( PROJ_Y_BAND_TOP_D ),
        .Y_BAND_BOT_N     ( PROJ_Y_BAND_BOT_N ),
        .Y_BAND_BOT_D     ( PROJ_Y_BAND_BOT_D ),
        .USE_X_BAND       ( PROJ_USE_X_BAND ),
        .X_BAND_LEFT_N    ( PROJ_X_BAND_LEFT_N ),
        .X_BAND_LEFT_D    ( PROJ_X_BAND_LEFT_D ),
        .X_BAND_RIGHT_N   ( PROJ_X_BAND_RIGHT_N ),
        .X_BAND_RIGHT_D   ( PROJ_X_BAND_RIGHT_D )
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
    wire [11:0] cam_px_cnt;
    wire [11:0] cam_py_cnt;

    video_xy_counter u_video_xy (
        .clk   ( clk ),
        .rst_n ( rst_n ),
        .vs_in ( vs_in ),
        .de_in ( de_in ),
        .x_cnt ( cam_px_cnt ),
        .y_cnt ( cam_py_cnt )
    );

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
        .px_cnt      ( cam_px_cnt ),
        .py_cnt      ( cam_py_cnt ),
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
        .px_cnt         ( cam_px_cnt ),
        .py_cnt         ( cam_py_cnt ),
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
