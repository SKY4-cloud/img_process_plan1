`timescale 1ns / 1ps

// Gray-world white balance — synthesizable, real-time capable.
//
// Per-frame R/G/B sums are accumulated during active video (de_in high).
// At the vsync falling edge a small FSM computes channel means (reciprocal
// multiplication — no hardware divider), the common gray target (÷3
// approximation), and per-channel Q8 gains via a 17-cycle restoring
// divider.  Gains from frame N apply to frame N+1 (standard 1-frame
// latency).  Total FSM runtime ≈ 60 clocks — well within vertical blanking.
//
// Output latency: 1 clock (registered vs/de/rgb).
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

    localparam [31:0] PIX_TOTAL = IMG_WIDTH * IMG_HEIGHT;

    // mean ≈ (sum × RECIP_PIX) >> RSHIFT   (ceiling reciprocal)
    localparam RSHIFT = 38;
    localparam [31:0] RECIP_PIX =
        ((64'd1 << RSHIFT) + PIX_TOTAL - 1) / PIX_TOTAL;

    /* -------- vsync falling edge -------- */
    reg vs_d;
    wire vs_fall = vs_d & ~vs_in;

    always @(posedge clk or negedge rst_n)
        if (!rst_n) vs_d <= 1'b0;
        else        vs_d <= vs_in;

    /* -------- pixel accumulators -------- */
    reg [31:0] sum_r, sum_g, sum_b;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            sum_r <= 0;  sum_g <= 0;  sum_b <= 0;
        end else if (vs_fall) begin
            sum_r <= 0;  sum_g <= 0;  sum_b <= 0;
        end else if (de_in) begin
            sum_r <= sum_r + {24'd0, r_in};
            sum_g <= sum_g + {24'd0, g_in};
            sum_b <= sum_b + {24'd0, b_in};
        end
    end

    /* -------- gain registers (Q8: 256 = ×1.0) -------- */
    reg [9:0] gain_r, gain_g, gain_b;

    /* -------- FSM states -------- */
    localparam [2:0]
        S_IDLE = 3'd0,
        S_MEAN = 3'd1,     // reciprocal multiply → means
        S_AVG  = 3'd2,     // ÷3 → mavg, prepare numerator
        S_DSET = 3'd3,     // divider setup (per channel)
        S_DRUN = 3'd4,     // restoring-division iteration
        S_DOUT = 3'd5;     // clamp & store gain

    reg [2:0]  st;
    reg [1:0]  ch;          // 0 = R, 1 = G, 2 = B
    reg [4:0]  dcnt;        // iteration counter 0..16

    reg [31:0] ls_r, ls_g, ls_b;       // latched sums
    reg [7:0]  mr, mg, mb;             // channel means
    reg [16:0] num;                     // mavg << 8 (gain numerator)

    // restoring divider registers
    reg [8:0]  drem;        // remainder (9-bit to hold shifted value)
    reg [16:0] dquo;        // quotient (shift-in from LSB)
    reg [16:0] dnum;        // numerator shift register (MSB out)
    reg [7:0]  dden;        // denominator

    /* -------- combinational helpers -------- */

    // mean = (latched_sum × RECIP_PIX) >> RSHIFT
    wire [63:0] pm_r = ls_r * RECIP_PIX;
    wire [63:0] pm_g = ls_g * RECIP_PIX;
    wire [63:0] pm_b = ls_b * RECIP_PIX;

    // ÷3 approximation: × 21846 >> 16  (21846/65536 ≈ 0.33331, error < 0.002%)
    wire [9:0]  sum3   = {2'd0, mr} + {2'd0, mg} + {2'd0, mb};
    wire [25:0] sum3_x = sum3 * 16'd21846;
    wire [7:0]  mavg   = sum3_x[23:16];

    // divider: trial = {rem[7:0], numerator_msb}
    wire [8:0]  dtrial = {drem[7:0], dnum[16]};
    wire        dtge   = dtrial >= {1'b0, dden};

    // channel mean mux
    wire [7:0]  ch_m = (ch == 2'd0) ? mr : (ch == 2'd1) ? mg : mb;

    // gain clamp
    wire [9:0]  clamped = (dquo < {7'd0, GAIN_MIN}) ? GAIN_MIN :
                          (dquo > {7'd0, GAIN_MAX}) ? GAIN_MAX :
                                                      dquo[9:0];

    /* -------- FSM -------- */
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            st     <= S_IDLE;
            ch     <= 0;
            dcnt   <= 0;
            gain_r <= 10'd256;
            gain_g <= 10'd256;
            gain_b <= 10'd256;
            ls_r   <= 0;  ls_g <= 0;  ls_b <= 0;
            mr     <= 0;  mg   <= 0;  mb   <= 0;
            num    <= 0;
            drem   <= 0;  dquo <= 0;
            dnum   <= 0;  dden <= 0;
        end else if (ENABLE) begin
            case (st)

            S_IDLE:
                if (vs_fall) begin
                    ls_r <= sum_r;
                    ls_g <= sum_g;
                    ls_b <= sum_b;
                    st   <= S_MEAN;
                end

            S_MEAN: begin
                mr <= pm_r[RSHIFT +: 8];
                mg <= pm_g[RSHIFT +: 8];
                mb <= pm_b[RSHIFT +: 8];
                st <= S_AVG;
            end

            S_AVG: begin
                num <= {1'b0, mavg, 8'd0};
                ch  <= 0;
                st  <= S_DSET;
            end

            S_DSET: begin
                dnum <= num;
                dden <= ch_m;
                drem <= 0;
                dquo <= 0;
                dcnt <= 0;
                if (ch_m == 0) begin
                    dquo <= 17'd256;
                    st   <= S_DOUT;
                end else
                    st <= S_DRUN;
            end

            S_DRUN: begin
                if (dtge) begin
                    drem <= dtrial - {1'b0, dden};
                    dquo <= {dquo[15:0], 1'b1};
                end else begin
                    drem <= dtrial;
                    dquo <= {dquo[15:0], 1'b0};
                end
                dnum <= {dnum[15:0], 1'b0};
                dcnt <= dcnt + 5'd1;
                if (dcnt == 5'd16)
                    st <= S_DOUT;
            end

            S_DOUT: begin
                case (ch)
                    2'd0:    gain_r <= clamped;
                    2'd1:    gain_g <= clamped;
                    default: gain_b <= clamped;
                endcase
                if (ch == 2'd2)
                    st <= S_IDLE;
                else begin
                    ch <= ch + 2'd1;
                    st <= S_DSET;
                end
            end

            default: st <= S_IDLE;

            endcase
        end
    end

    /* -------- gain application -------- */
    wire [17:0] pr = r_in * gain_r;
    wire [17:0] pg = g_in * gain_g;
    wire [17:0] pb = b_in * gain_b;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            vs_out <= 0;  de_out <= 0;
            r_out  <= 0;  g_out  <= 0;  b_out <= 0;
        end else begin
            vs_out <= vs_in;
            de_out <= de_in;
            if (!ENABLE) begin
                r_out <= r_in;
                g_out <= g_in;
                b_out <= b_in;
            end else begin
                r_out <= |pr[17:16] ? 8'd255 : pr[15:8];
                g_out <= |pg[17:16] ? 8'd255 : pg[15:8];
                b_out <= |pb[17:16] ? 8'd255 : pb[15:8];
            end
        end
    end

endmodule
