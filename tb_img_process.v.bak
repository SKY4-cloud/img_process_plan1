`timescale 1ns / 1ps

module tb_img_process();

parameter IMG_WIDTH  = 640;
parameter IMG_HEIGHT = 480;
parameter PIXEL_NUM  = IMG_WIDTH * IMG_HEIGHT;

parameter ROI_OUT_W  = 64;
parameter ROI_OUT_H  = 32;
parameter ROI_PIXELS = ROI_OUT_W * ROI_OUT_H;

parameter SIM_FRAMES = 3;

parameter H_SYNC  = 10;
parameter H_BACK  = 10;
parameter H_DISP  = IMG_WIDTH;
parameter H_FRONT = 10;
parameter H_TOTAL = H_SYNC + H_BACK + H_DISP + H_FRONT;

parameter V_SYNC  = 2;
parameter V_BACK  = 40;
parameter V_DISP  = IMG_HEIGHT;
parameter V_FRONT = 2;
parameter V_TOTAL = V_SYNC + V_BACK + V_DISP + V_FRONT;

reg         clk;
reg         rst_n;

reg         cam_vsync;
reg         cam_hsync;
reg         cam_de;
reg  [23:0] cam_data;

wire        out_vsync;
wire        out_de;
wire [7:0]  out_data;

wire        out_osd_vs;
wire        out_osd_de;
wire [23:0] out_osd_rgb;

wire        roi_vs;
wire        roi_de;
wire [23:0] roi_rgb;
wire        roi_done;

reg [11:0]  h_cnt;
reg [11:0]  v_cnt;
reg [31:0]  pixel_cnt;

reg [23:0]  img_mem [0:PIXEL_NUM-1];

integer     file_out;

initial begin
    clk = 0;
    forever #10 clk = ~clk;
end

initial begin
    rst_n = 0;
    #100;
    rst_n = 1;
end

initial begin
    $readmemh("image_in.txt", img_mem);

    file_out = $fopen("image_out.txt", "w");
    if (!file_out) begin
        $display("[!] ERROR: Cannot create image_out.txt");
        $stop;
    end
end

wire de_comb = ((h_cnt >= H_SYNC + H_BACK) && (h_cnt < H_SYNC + H_BACK + H_DISP) &&
                (v_cnt >= V_SYNC + V_BACK) && (v_cnt < V_SYNC + V_BACK + V_DISP));

always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        h_cnt     <= 0;
        v_cnt     <= 0;
        cam_vsync <= 0;
        cam_hsync <= 0;
        cam_de    <= 0;
        cam_data  <= 24'd0;
        pixel_cnt <= 0;
    end else begin
        if (h_cnt == H_TOTAL - 1) begin
            h_cnt <= 0;
            if (v_cnt == V_TOTAL - 1)
                v_cnt <= 0;
            else
                v_cnt <= v_cnt + 1;
        end else begin
            h_cnt <= h_cnt + 1;
        end

        cam_hsync <= (h_cnt < H_SYNC) ? 1'b1 : 1'b0;
        cam_vsync <= (v_cnt < V_SYNC) ? 1'b1 : 1'b0;

        cam_de <= de_comb;

        if (de_comb) begin
            cam_data  <= img_mem[pixel_cnt];
            if (pixel_cnt == PIXEL_NUM - 1)
                pixel_cnt <= 0;
            else
                pixel_cnt <= pixel_cnt + 1;
        end else begin
            cam_data <= 24'd0;
        end
    end
end

image_process_wrapper #(
    .IMG_WIDTH      ( IMG_WIDTH  ),
    .IMG_HEIGHT     ( IMG_HEIGHT ),
    .PROJ_MIN_AREA  ( 2000 ),
    .ROI_OUT_W      ( ROI_OUT_W ),
    .ROI_OUT_H      ( ROI_OUT_H )
) u_image_process_wrapper (
    .clk        ( clk ),
    .rst_n      ( rst_n ),

    .vs_in      ( cam_vsync ),
    .de_in      ( cam_de ),
    .r_in       ( cam_data[23:16] ),
    .g_in       ( cam_data[15:8]  ),
    .b_in       ( cam_data[7:0]   ),

    .post_vs   ( out_vsync ),
    .post_de   ( out_de ),
    .post_data ( out_data ),

    .osd_vs    ( out_osd_vs ),
    .osd_de    ( out_osd_de ),
    .osd_rgb   ( out_osd_rgb ),

    .roi_vs         ( roi_vs ),
    .roi_de         ( roi_de ),
    .roi_rgb        ( roi_rgb ),
    .roi_frame_done ( roi_done )
);

reg [11:0] frame_cnt = 0;
always @(negedge out_vsync) begin
    if (!rst_n)
        frame_cnt <= 0;
    else
        frame_cnt <= frame_cnt + 1;
end

always @(posedge clk) begin
    if (out_de && frame_cnt == SIM_FRAMES - 1) begin
        $fwrite(file_out, "%02x\n", out_data);
    end
end

integer rgb_file;
integer roi_file;

initial begin
    rgb_file = $fopen("image_out_rgb.txt", "w");
    if (!rgb_file) begin
        $display("[!] ERROR: Cannot create image_out_rgb.txt");
        $stop;
    end
    roi_file = $fopen("image_out_roi.txt", "w");
    if (!roi_file) begin
        $display("[!] ERROR: Cannot create image_out_roi.txt");
        $stop;
    end
end

reg [3:0] osd_frame_cnt = 0;
always @(posedge out_osd_vs) begin
    osd_frame_cnt <= osd_frame_cnt + 1;
end

always @(posedge clk) begin
    if (out_osd_de && osd_frame_cnt == SIM_FRAMES - 1) begin
        $fwrite(rgb_file, "%02x%02x%02x\n",
                out_osd_rgb[23:16], out_osd_rgb[15:8], out_osd_rgb[7:0]);
    end
end

reg [3:0] roi_frame_cnt = 0;
always @(posedge roi_vs) begin
    roi_frame_cnt <= roi_frame_cnt + 1;
end

always @(posedge clk) begin
    if (roi_de && (roi_frame_cnt == SIM_FRAMES - 1)) begin
        $fwrite(roi_file, "%02x%02x%02x\n",
                roi_rgb[23:16], roi_rgb[15:8], roi_rgb[7:0]);
    end
end

always @(posedge frame_cnt[0] or posedge frame_cnt[1] or
         posedge frame_cnt[2] or posedge frame_cnt[3]) begin
    $display("[*] Frame %0d / %0d completed (sim time = %0t)",
             frame_cnt, SIM_FRAMES, $time);
end

always @(negedge out_vsync) begin
    if (frame_cnt == SIM_FRAMES - 1) begin
        $display("[+] Simulation finished: %0d frames processed.", SIM_FRAMES);
        $fclose(file_out);
        $fclose(rgb_file);
        $fclose(roi_file);
        #100;
        $stop;
    end
end

endmodule
