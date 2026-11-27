<!--
  Source: https://n64brew.dev/wiki/Video_Interface
  Authors: N64brew Wiki contributors
  License: CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/)
-->

The Video Interface (or '''VI''') is one of multiple I/O interfaces in the [[Reality Coprocessor|RCP]], which configures different parts of the console's video rendering and output. It provides significant flexibility to support NTSC, PAL, and M-PAL, using the same chips and registers. All memory-mapped registers are 32 bits wide and should always be written a full word (32 bits) at a time.

= Video DAC =
The Video Interface emits a 28-bit signal, multiplexed over a 7-bit bus clocked at roughly 49MB/sec, with one extra signal ("DSYNC") providing framing. This is received by the [[Video DAC]], which converts this into standard-definition video.

Since the bus is multiplexed 4 ways, the resulting pixel clock is 1/4 the data rate, roughly 12.3 megapixels/sec. This is close to ideal for 640 pixels of video in the NTSC or PAL active area. For more details about the bus contents, see [[Video DAC]]

= Video Standards =
The video standards send more than just pixel data both on each line and with additional lines at the top and bottom of a frame.

= Hardware =
Most of the Video Interface is implemented inside the RCP (Reality CoProcessor), although there is a Video DAC (Digital Analog Converter) on the mainboard, and another encoder IC (ENC-NUS) which which appears to manage some of the signal differences between Composite and S-Video Output.

= Configuration Registers =
Memory mapped registers are used to configure the Video Interface. The base address for these registers is <code>0x0440 0000</code>, also known as VI_BASE. However, because all memory accesses in the CPU are made using virtual addresses, the following addresses must be offset appropriately. For non-cached reads/writes, add <code>0xA000 0000</code> to the address. As an example, to directly write to the VI_CTRL register, use address <code>0xA440 0000</code>.

'''Table Notation:'''
<pre>
R = Readable bit
W = Writable bit
U = Undefined/Unused bit
-n = Default value n at power on
<x:y> = Specifies bits x to y, inclusively</pre>
==== <span style="display:none;">0x0440 0000 - VI_CTRL ====
----
{{#invoke:Register table|head|1200px|VI_CTRL <code>0x0440 0000</code>}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|23:16}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || RW-0
|-
| — || — || — || — || — || — || — || style="font-size: 60%;" | DEDITHER_FILTER_ENABLE
{{#invoke:Register table|row|15:8}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || U-0 || RW-0 || RW-0
|-
| colspan="4" | PIXEL_ADVANCE[3:0] || KILL_WE || — || colspan="2" | AA_MODE[1:0]
{{#invoke:Register table|row|7:0}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| TEST_MODE || SERRATE || style="font-size: 70%;" | VBUS_CLOCK_ENABLE || DIVOT_ENABLE || GAMMA_ENABLE || style="font-size: 70%;" | GAMMA_DITHER_ENABLE || colspan="2" | TYPE[1:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-17 | Undefined | Initialized to <code>0</code>
| 16 | DEDITHER_ENABLE | Dedither Enable bit   <br>1 {{=}} Dedithering (aka "dither filter") is enabled; normally used for 16-bit framebuffers to try to reconstruct a 32-bit image. Notice that this filter only works correctly when <code>AA_MODE</code> is set to either <code>REPLICATE</code> or <code>AA_ALWAYS</code>.  <br>0 {{=}} Dedithering is disabled (normally used for 32-bit color)
| 15-12 | PIXEL_ADVANCE[3:0] | Use <code>0b0011</code> for most effective behavior on N64. On the iQue Player a pixel advance of <code>0b0011</code> creates video glitches, applications typically use <code>0b0001</code> instead.
| 11 | KILL_WE | Diagnostics only, possibly kills VI DMA writes to line buffers making them safe to access via the test registers.
| 10 | Undefined | Initialized to <code>0</code>
| 9-8 | AA_MODE[1:0] | Anti-Alias Mode   <br>11 / REPLICATE {{=}} AA and resampling disabled, replicate pixels without interpolation   <br>10 / RESAMPLE {{=}} AA disabled, resampling enabled, and operate as if everything is covered   <br>01 / AA_NEEDED {{=}} AA enabled, resampling enabled, and only fetches extra lines as needed   <br>00 / AA_ALWAYS {{=}} AA enabled, resampling enabled, and will always fetch extra lines.
| 7 | TEST_MODE | Diagnostics only, enables usage of the line buffer test registers VI_TEST_ADDR/VI_STAGED_DATA. KILL_WE should also be set to avoid access races between the VI and CPU.
| 6 | SERRATE | Required if interlacing, permitted when progressive, often disabled <br>1 {{=}} Enabled <br>0 {{=}} Disabled
| 5 | VBUS_CLOCK_ENABLE | Vbus Clock Enable   <br>1 {{=}} Enabled   <br>0 {{=}} Disabled <br>{{spaces|4}}'''''Warning: Always leave disabled!''' Setting this bit enables a second driver, which will output on the same pin as another driver, possibly causing physical console damage.''
| 4 | DIVOT_ENABLE | Fixes minor artifacts left over from anti-aliasing (more details below)   <br>1 {{=}} Enabled (usually used if AA is enabled)   <br>0 {{=}} Disabled
| 3 | GAMMA_ENABLE | Fixes non-linear gamma in TV screens (more details below)   <br>1 {{=}} Enabled   <br>0 {{=}} Disabled
| 2 | GAMMA_DITHER_ENABLE | Adds randomized noise to the video output, in the least significant bits to remove mach banding artifacts   <br>1 {{=}} Enabled (usually set unless banding artifacts are desired for extra effect)   <br>0 {{=}} Disabled
| 1-0 | TYPE[1:0] | Video pixel size, also known as color bit depth   <br>11 {{=}} 8/8/8/8 (32 bit color)   <br>10 {{=}} 5/5/5/3 (16 bit color, technically 18 bits wide)   <br>01 {{=}} reserved   <br>00 {{=}} Turned off (no data and no sync, TV screens will either show static or nothing)
}}
'''Extra Details:'''
: '''DEDITHER_ENABLE'''
:: When enabled, the VI will run a de-dithering algorithm, trying to reverse the effects of dithering on each pixel to produce an higher resolution color information on the analog output. This is useful when the framebuffer is 16-bit and has been dithered while drawing. To do so, VI looks at the 8 neighbors around each pixel and perform an error correction; the algorithm used works best with images that have been dithered using the "Magic Square" dithering algorithm (that the RDP can be configured to do). The VI does de-dedithering only on pixels where coverage is full; on pixels with partial coverage, the standard AA algorithm is performed. '''NOTE''': this filter requires <code>AA_MODE</code> to be set to either <code>AA_ALWAYS</code> (always fetch extra lines) or <code>REPLICATE</code> (no AA/resampling); the other two configurations are not compatible, and the image becomes corrupted by vertical streaks ([https://github.com/DragonMinded/libdragon/issues/159 as seen here]).
: '''DIVOT_ENABLE'''
:: When enabled, this feature fixes artifacts that the anti-aliasing algorithm leaves behind. The median color of three neighboring pixels, from any pixels on or next to silhouette edges, is selected to be displayed in place of the center pixel. Effectively removing any one pixel divots that can be seen in some fractal-based terrains. The anti-aliasing function encounters issues when multiple fragments occur on a single pixel. Since this filter is only used on edges, and not the surface of an object, texture details will not be affected. Be aware that bad quality effects can occur when the ''decal line'' rendering mode is used in conjunction with this filter, as the rendering mode generates edges that the filter can detect.
: '''GAMMA_ENABLE'''
:: This feature is used to correct non-linear gamma found in TV screens (although this may have changed in modern TV's). To do this, the feature square roots the linear color space that the rendering pipeline uses. TV screens will raise these color values to the power of 2.2 to 2.4, which leaves a residual gamma behind of around 1.1 to 1.2. This residual value is actually preferred as a gamma slightly above 1.0 will generate more color accurate images when the TV is in darker than normal rooms. When using MPEG or JPG images, the gamma correction is included in the image data, so this feature should be turned off accordingly.
: '''SERRATE'''
:: Serration is one the two required components for interlaced display. The other required component is an odd number of half-scanlines. Serration is required in order to delay one of the two fields by half a scanline. Together, this visually displays the beam of light "between" the scanlines of the other field. To obtain the correct effect, this must be complement by a software tweak, that is, the odd field must be adjusted to "scroll up" the contents by half a scanline as well, because otherwise it's not displayed properly wrt the original framebuffer image. To do so, it is normally sufficient to offset '''Y_OFFSET''' by '''Y_SCALE / 2''' (considering the '''Y_SCALE''' is the fixed point step representing one scanline in the framebuffer). Note that '''Y_OFFSET''' is limited to fractional values though, so if the offset goes beyond '''1.0''', the integer part must be implemented by offsetting '''VI_ORIGIN''' instead.

==== <span style="display:none;">0x0440 0004 - VI_ORIGIN ====
----
{{#invoke:Register table|head|550px|VI_ORIGIN <code>0x0440 0004</code>}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|23:16}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | ORIGIN[23:16]
{{#invoke:Register table|row|15:8}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | ORIGIN[15:8]
{{#invoke:Register table|row|7:0}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | ORIGIN[7:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-24 | Undefined | Initialized to <code>0</code>
| 23-0 | ORIGIN[23:0] | RDRAM base address of the video output Frame Buffer. This can be changed as needed to implement double or triple buffering.
}}
'''Extra Details:'''
: ORIGIN must be a multiple of 8 (i.e. ORIGIN[2:0] must be 0). Otherwise the VI output may be noisy, shifted, or weirdly interleaved.
: You can change ORIGIN mid-frame during horizontal blank. Notice however that VI internally keeps the running offset in the framebuffer since the frame started (accumulating VI_V_SCALE for each scanline) and that offset is *not* reset when ORIGIN changes. So the new framebuffer will be
sampled starting from the same byte offset that the previous framebuffer would have sampled at.

==== <span style="display:none;">0x0440 0008 - VI_WIDTH ====
----
{{#invoke:Register table|head|550px|VI_WIDTH <code>0x0440 0008</code>}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|23:16}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|15:8}}
| U-0 || U-0 || U-0 || U-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| — || — || — || — || colspan="4" | WIDTH[11:8]
{{#invoke:Register table|row|7:0}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | WIDTH[7:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-12 | Undefined | Initialized to <code>0</code>
| 11-0 | WIDTH[11:0] | This is the width in pixels of the frame buffer if you draw to the frame buffer based on a different width than what is given here the image will drift with each line to the left or right. The common values are 320 and 640, the maximum value is 4095. The same value would also be used on drawing commands for clipping or scissors. This can also be used with High Res interlacing modes to change the odd and even lines of the frame buffer to be drawn to screen by doubling the width of this value and changing the VI_ORIGIN register to the odd or even field being displayed. 
}}
'''Extra Details:'''
: WIDTH must be a multiple of 2 (if 32bpp) or 4 (if 16bpp) such that the number of bytes from one scanline to the next is a multiple of 8. The same caveats about VI_ORIGIN apply here, but incorrect display will only happen on some scanlines.
: Just like VI_ORIGIN, you can change VI_WIDTH mid-frame during horizontal blank.
: Values of WIDTH < 8 can sometimes cause VI crashes. This is not fully understood yet, see [https://github.com/DragonMinded/libdragon/issues/759 this libdragon issue] for details.

==== <span style="display:none;">0x0440 000C - VI_V_INTR ====
----
{{#invoke:Register table|head|550px|VI_V_INTR <code>0x0440 000C</code>}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|23:16}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|15:8}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || RW-1 || RW-1
|-
| — || — || — || — || — || — || colspan="2" | V_INTR[9:8]
{{#invoke:Register table|row|7:0}}
| RW-1 || RW-1 || RW-1 || RW-1 || RW-1 || RW-1 || RW-1 || RW-1
|-
| colspan="8" | V_INTR[7:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-10 | Undefined | Initialized to <code>0</code>
| 9-1 | V_INTR[9:0] | When VI_V_CURRENT reaches this half-line number, a VI Interrupt is triggered. Both libultra and libdragon set this to the value 2, which causes an interrupt to be triggered on the second line of vblank.<br>Default value of <code>0x3FF</code>
}}

The actual behavior of V_INTR depends on whether interlaced mode is on or off. The actual hardware trigger for the change in behavior is bit 0 of VI_V_TOTAL, that is, whether the total number of configured half-lines (<code>VI_V_TOTAL</code>) is odd or even, which is part of a correct interlacing configuration. Notice that the state of serration (<code>VI_CTRL.SERRATE</code>) does not affect VI_V_INTR behavior per-se.

When <code>VI_V_TOTAL</code> bit 0 is 1 (progressive modes), bit 0 of <code>VI_V_INTR</code> is effectively ignored: the interrupt will trigger when <code>V_INTR[9:1]</code> matches <code>VI_V_CURRENT[9:1]</code>, irrespective of the two LSBs.

When <code>VI_V_TOTAL</code> bit 0 is 0 (interlaced modes), bit 0 of <code>VI_V_INTR</code> does have an effect:

* If bit 0 is set to 1, the behavior is the expected one: interrupts happen when <code>VI_V_INTR[9:1]</code> matches <code>VI_V_CURRENT[9:1].</code> For instance, setting <code>VI_V_INTR=15</code> can be used to request an interrupt on line 7 of the screen. The interrupt will trigger when <code>VI_V_CURRENT</code> is either 14 (line 7, field 0) or 15 (line 7, field 1).
* If bit 0 is set to 0, interrupts in odd fields are triggered one line before the actual match. For instance, setting <code>VI_V_INTR=14</code> causes an interrupt to generated when <code>VI_V_CURRENT</code> is either 14 (line 7, field 0) or 13 (line 6, field 1). This appears to be a hardware bug, probably a side effect on internal timings. An important case to consider for this bug is when <code>VI_V_INTR</code> is set 0: in that case, the interrupt will happen on the last line of the previous even field. For instance, in a default PAL configuration with 525 lines, <code>VI_V_INTR=0</code> will cause an interrupt when <code>VI_V_CURRENT</code> is either 0 (line 0, field 0), or 524 (line 262, field 0), though the latter is supposed to be the one to signal the beginning of the odd field. In this case, reading the field number in the interrupt handler would always result in an even field.

When the VI is turned off (<code>VI_CTRL.TYPE</code> is 0), no VI interrupt is ever generated.

==== <span style="display:none;">0x0440 0010 - VI_V_CURRENT ====
----
{{#invoke:Register table|head|550px|VI_V_CURRENT <code>0x0440 0010</code>}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|23:16}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|15:8}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || RW-0 || RW-0
|-
| — || — || — || — || — || — || style="font-size: 88%;" colspan="2" | V_CURRENT[8:7]
{{#invoke:Register table|row|7:0}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="7" | V_CURRENT[6:0] || FIELD
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-10 | Undefined | Initialized to <code>0</code>
| 9-1 | V_CURRENT | The current half line, sampled once per line. 
| 0 | V_FIELD | Field number. In interlaced modes, it alternates between 0 or 1 after each frame. In non-interlaced modes, it stays constant (it can be either 0 or 1). 
}}

Writing anything to this register clears the currently triggered VI Interrupt.

When <code>V_V_TOTAL</code> bit 0 is 1 (progressive modes), the <code>V_CURRENT</code> field counts up from 0 to half of the number of active display lines, rounded up. For instance, in a default PAL configuration of 525 vertical lines (see <code>VI_V_VIDEO</code>), it will count from 0 to 262, included. <code>FIELD</code> will normally be 0 in these modes, so the full registers values will be 0x0, 0x2, 0x4, ..., 0x20C. When changing resolutions from interlaced to progressive, sometimes <code>FIELD</code> stays fixed to 1 instead, in which case the full register values will be 0x1, 0x3, 0x5, ..., 0x20D.

When <code>VI_V_TOTAL</code> bit 0 is 0 (interlaced modes), the behavior is similar but the <code>FIELD</code> value will alternate between 0 and 1 after each run. The even field will be one line longer in case the active vertical display area is odd. So, assuming the same PAL configuration of 525 vertical lines, the full register values will be: 0x0, 0x2, 0x4, ..., 0x20C, 0x1, 0x3, 0x5, ..., 0x20B.

The register value changes right at the beginning of the hsync period.

When the VI is turned off (<code>VI_CTRL.TYPE</code> is 0), this register is fixed to 0, and never changes.

==== <span style="display:none;">0x0440 0014 - VI_BURST ====
----
{{#invoke:Register table|head|550px|VI_BURST <code>0x0440 0014</code>}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| — || — || colspan="6" | BURST_START[9:4]
{{#invoke:Register table|row|23:16}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="4" | BURST_START[3:0] || colspan="4" | VSYNC_HEIGHT[3:0]
{{#invoke:Register table|row|15:8}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | BURST_WIDTH[7:0]
{{#invoke:Register table|row|7:0}}
| RW-1 || RW-1 || RW-0 || RW-1 || RW-0 || RW-0 || RW-0 || RW-1
|-
| colspan="8" | HSYNC_WIDTH[7:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-30 | Undefined | Initialized to <code>0</code>
| 29-20 | BURST_START[9:0] | Start of color burst in pixels from hsync
| 19-16 | VSYNC_HEIGHT[3:0] | One less than the vertical sync duration in half lines
| 15-8 | BURST_WIDTH[7:0] | Color burst width in pixels
| 7-0 | HSYNC_WIDTH[7:0] | Horizontal sync width in pixels<br>Default value of <code>0x01</code>
}}
'''Examples:'''
: NTSC @ any resolution is <code>0x03E52239</code>
:* horizontal sync width in pixels:  57 (decimal)
:* color burst width in pixels:  34 (decimal)
:* vertical sync height in half lines: 5 (decimal) (and thus 6 half-lines)
:* start of color burst in pixels from h-sync: 62 (decimal)
: PAL @ any resolution is <code>0x0404233A</code>
:* horizontal sync width in pixels:  58 (decimal)
:* color burst width in pixels:  35 (decimal)
:* vertical sync height in half lines: 4 (decimal) (and thus 5 half-lines)
:* start of color burst in pixels from h-sync: 64 (decimal)

==== <span style="display:none;">0x0440 0018 - VI_V_TOTAL ====
----
{{#invoke:Register table|head|550px|VI_V_TOTAL<ref>This register used to be called VI_V_SYNC, but was changed to better reflect its actual meaning.</ref> <code>0x0440 0018</code>}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|23:16}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|15:8}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || RW-0 || RW-0
|-
| — || — || — || — || — || — || colspan="2" | V_TOTAL[9:8]
{{#invoke:Register table|row|7:0}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | V_TOTAL[7:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-10 | Undefined | Initialized to <code>0</code>
| 9-0 | V_TOTAL[9:0] | One less than the total number of visible and non-visible half-lines. This should match either NTSC/MPAL (non-interlaced: <code>525</code>, interlaced: <code>524</code>) or PAL (non-interlaced: <code>625</code>, interlaced: <code>624</code>)
}}

Interlaced modes requires an odd number of scanlines to be configured (that is, an even number written to the register, given that it holds one less than the actual wanted number), in addition to serration being turned on (VI_CTRL.SERRATE). So it is normal to write to this register to switch between interlaced and progressive modes.

==== <span style="display:none;">0x0440 001C - VI_H_TOTAL ====
----
{{#invoke:Register table|head|550px|VI_H_TOTAL<ref>This register used to be called VI_H_SYNC, but was changed to better reflect its actual meaning.</ref> <code>0x0440 001C</code>}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|23:16}}
| U-0 || U-0 || U-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| — || — || — || colspan="5" | LEAP[4:0]
{{#invoke:Register table|row|15:8}}
| U-0 || U-0 || U-0 || U-0 || RW-1 || RW-1 || RW-1 || RW-1
|-
| — || — || — || — || colspan="4" | H_TOTAL[11:8]
{{#invoke:Register table|row|7:0}}
| RW-1 || RW-1 || RW-1 || RW-1 || RW-1 || RW-1 || RW-1 || RW-1
|-
| colspan="8" | H_TOTAL[7:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-21 | Undefined | Initialized to <code>0</code>
| 20-16 | LEAP[4:0] | 5-bit leap pattern. PAL standard value is <code>0x15</code>
| 15-12 | Undefined | Initialized to <code>0</code>
| 11-0 | H_TOTAL[11:0] | One less than the total length of a scanline in 1/4 pixel units. Standard values are NTSC (<code>3093</code>), PAL (<code>3177</code>), MPAL progressive (<code>3089</code>), and MPAL interlaced (<code>3088</code>)<br>Default value is <code>2047</code> (</code>0x7FF</code>)
}}

'''Extra Details:'''
: LEAP chooses whether to use LEAP_A or LEAP_B on each vsync repeating every five vsyncs. The NTSC default (0) means "always use LEAP_A". The PAL default (0x15) means "alternate using LEAP_B, LEAP_A, LEAP_B, LEAP_A, LEAP_B" and repeat.
: Derivation of numbers: 
:: NTSC has 227.5 chroma periods per scanline. NTSC N64 has 13.6 VI clocks per chroma period. 227.5 × 13.6 = 3094
:: MPAL has 227.25 chroma periods per scanline. MPAL N64 has 13.6 VI clocks per chroma period. 227.25 x 13.6 = 3090.6
:: PAL (European) has 283.7516 chroma periods per scanline. PAL N64 has 11.2 clocks per chroma period. 283.75 x 11.2 = 3178
: H_TOTAL is also used by the RDRAM Interface for refresh timings. As the default is notably shorter than regular video modes, there will be a noticeable impact to memory bandwidth until H_TOTAL is configured to a valid video mode.  

==== <span style="display:none;">0x0440 0020 - VI_H_TOTAL_LEAP ====
----
{{#invoke:Register table|head|550px|VI_H_TOTAL_LEAP<ref>This register used to be called VI_H_SYNC_LEAP, but was changed to better reflect its actual meaning.</ref> <code>0x0440 0020</code>}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || U-0 || U-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| — || — || — || — || colspan="4" | LEAP_A[11:8]
{{#invoke:Register table|row|23:16}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | LEAP_A[7:0]
{{#invoke:Register table|row|15:8}}
| U-0 || U-0 || U-0 || U-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| — || — || — || — || colspan="4" | LEAP_B[11:8]
{{#invoke:Register table|row|7:0}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | LEAP_B[7:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-28 | Undefined | Initialized to <code>0</code>
| 27-16 | LEAP_A[11:0] | Special scanline length (H_TOTAL), when LEAP{{=}}0
| 15-12 | Undefined | Initialized to <code>0</code>
| 11-0 | LEAP_B[11:0] | Special scanline length (H_TOTAL), when LEAP{{=}}1
}}
'''Extra Details:'''
: LEAP_n specifies an alternate scanline length (H_TOTAL alternative value) for one scanline during vsync. Values larger than H_TOTAL specify the length of the second scanline of vsync. Values smaller than H_TOTAL specify the length of the first scanline of vsync and have a variety of undesired side effects, such as skipping one hsync entirely or leaving csync erroneously high for one whole scanline. Serration changes these effects subtly.
: Specifically, a counter is started at the start of vsync. When that counter is equal to LEAP_n, the VI starts or restarts the second scanline of vsync without changing the status of the csync bit.

: The default PAL values of LEAP (<code>0x15</code>), LEAP_A (<code>3182</code>), and LEAP_B (<code>3183</code>) add PAL's nominal "one extra chroma period per 625 whole scanlines emitted" when averaged. 6 + 5 + 6 + 5 + 6 = 5.6; divide 5.6 by 11.2 VI clocks per chroma period = 1/2 chroma period per field.

==== <span style="display:none;">0x0440 0024 - VI_H_VIDEO ====
----
{{#invoke:Register table|head|550px|VI_H_VIDEO <code>0x0440 0024</code>}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || RW-0 || RW-0
|-
| — || — || — || — || — || — || colspan="2" | H_START[9:8]
{{#invoke:Register table|row|23:16}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | H_START[7:0]
{{#invoke:Register table|row|15:8}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || RW-0 || RW-0
|-
| — || — || — || — || — || — || colspan="2" | H_END[9:8]
{{#invoke:Register table|row|7:0}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | H_END[7:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-26 | Undefined | Initialized to <code>0</code>
| 25-16 | H_START[9:0] | Start of the active video image, in screen pixels. Typical values: NTSC (<code>108</code>) or PAL (<code>128</code>)
| 15-10 | Undefined | Initialized to <code>0</code>
| 9-0 | H_END[9:0] | End of the active video image, in screen pixels from hsync. Typical values: NTSC (<code>748</code>) or PAL (<code>768</code>)
}}
'''Extra Details:'''
: H_START specifies when VI evaluation starts. The screen remains blanked for several pixels afterwards, while the VI loads values from RAM for filtering, even if '''AA_MODE''' is set to '''REPLICATE'''.
: H_END specifies the first black pixel on the right end of each scanline.
: Setting H_START = H_END = 0 blanks the display output (full black, no picture displayed) but keeps the VI fully active (line counter will increment, interrupts will trigger, etc.). This is different from setting VI_CTRL.TYPE=0, which instead will totally stop VI activity (no output signal).
: Setting VI_H_VIDEO while display is in progress can sometimes cause the VI to hang (normally, a striped picture will be displayed). The registers should only be changed during vertical blank.
: It is instead possible to change VI_H_VIDEO mid-frame as long as it strictly happens within horizontal blank.

==== <span style="display:none;">0x0440 0028 - VI_V_VIDEO ====
----
{{#invoke:Register table|head|550px|VI_V_VIDEO <code>0x0440 0028</code>}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || RW-0 || RW-0
|-
| — || — || — || — || — || — || colspan="2" | V_START[9:8]
{{#invoke:Register table|row|23:16}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | V_START[7:0]
{{#invoke:Register table|row|15:8}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || RW-0 || RW-0
|-
| — || — || — || — || — || — || colspan="2" | V_END[9:8]
{{#invoke:Register table|row|7:0}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | V_END[7:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-26 | Undefined | Initialized to <code>0</code>
| 25-16 | V_START[9:0] | Start of the active video image, in screen half-lines. Typical values: NTSC (<code>0x025</code>) or PAL (<code>0x05F</code>)
| 15-10 | Undefined | Initialized to <code>0</code>
| 9-0 | V_END[9:0] | End of the active video image, in screen half-lines from vsync. Typical values: NTSC (<code>0x1FF</code>) or PAL (<code>0x239</code>)
}}
'''Extra Details:'''
: Mid-frame changes to VI_V_VIDEO seem to be totally ignored by VI, including changes to V_END, as if the register is latched internally at the beginning of the frame.
==== <span style="display:none;">0x0440 002C - VI_V_BURST ====
----
{{#invoke:Register table|head|700px|VI_V_BURST <code>0x0440 002C</code>}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || RW-0 || RW-0
|-
| — || — || — || — || — || — || style="font-size: 90%;" colspan="2" | V_BURST_START[9:8]
{{#invoke:Register table|row|23:16}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | V_BURST_START[7:0]
{{#invoke:Register table|row|15:8}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || RW-0 || RW-0
|-
| — || — || — || — || — || — || style="font-size: 90%;" colspan="2" | V_BURST_END[9:8]
{{#invoke:Register table|row|7:0}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | V_BURST_END[7:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-26 | Undefined | Initialized to <code>0</code>
| 25-16 | V_BURST_START[9:0] | Start of the color burst enable, in half-lines. Typical values: NTSC (<code>0x00E</code>) or PAL (<code>0x009</code>)
| 15-10 | Undefined | Initialized to <code>0</code>
| 9-0 | V_BURST_END[9:0] | End of the color burst enable, in half-lines. Typical values: NTSC (<code>0x204</code>) or PAL (<code>0x26B</code>)
}}
==== <span style="display:none;">0x0440 0030 - VI_X_SCALE ====
----
{{#invoke:Register table|head|550px|VI_X_SCALE <code>0x0440 0030</code>}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || U-0 || U-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| — || — || — || — || colspan="4" | X_OFFSET[11:8]
{{#invoke:Register table|row|23:16}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | X_OFFSET[7:0]
{{#invoke:Register table|row|15:8}}
| U-0 || U-0 || U-0 || U-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| — || — || — || — || colspan="4" | X_SCALE[11:8]
{{#invoke:Register table|row|7:0}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | X_SCALE[7:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-28 | Undefined | Initialized to <code>0</code>
| 27-16 | X_OFFSET[11:0] | Horizontal subpixel offset ([[#Fixed-Point Format|2.10 format]])
| 15-12 | Undefined | Initialized to <code>0</code>
| 11-0 | X_SCALE[11:0] | 1/horizontal scale up factor (2.10 format)
}}
'''Extra Details:'''
: It is possible to change VI_X_SCALE mid-frame during horizontal blank.
===== Errata =====
* If [[#0x0440_0000_-_VI_CTRL|AA_MODE]] = REPLICATE (resampling disabled), [[#0x0440_0000_-_VI_CTRL|TYPE]] = 10 (16-bit), X_SCALE is 0x200 or lower, and H_START is less than 128, the VI generates invalid output, consisting of the first 64 pixels from the framebuffer from the current line, then 64 pixels of garbage, and these two repeat for the rest of each scanline. A common case where this can happen is NTSC units (where H_START is usually 96) with a standard framebuffer of 320x240 (X_SCALE=0x200). For this very common situation, the simplest workaround is to activate resampling or, if the wanted scale was exactly 0x200 (for a 320 pixel wide framebuffer), use 0x201 instead which is guaranteed to not introduce any visual difference, but does not trigger the bug.
* The previous bug can also be triggered with resampling is set to [[#0x0440_0000_-_VI_CTRL|AA_MODE]] = RESAMPLE (resampling enabled, AA disabled) with the same constraints X_SCALE < 0x200 and H_START < 128, but the additional constraint of WIDTH < 8. Compared to the previous incantation which always reproduces, this crash also requires specific timing to trigger. See [https://github.com/DragonMinded/libdragon/issues/759 this libdragon issue] for more information.
* If X_SCALE is higher than 0x800 (32bpp) or 0xE00 (16bpp), the scaler renders incorrect pixels, with specifics depending on depth. This appears to be due to exceeding the number of VI fetches allocated per scanline.

==== <span style="display:none;">0x0440 0034 - VI_Y_SCALE ====
----
{{#invoke:Register table|head|550px|VI_Y_SCALE <code>0x0440 0034</code>}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || U-0 || U-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| — || — || — || — || colspan="2" | unused || colspan="2" | Y_OFFSET[9:8]
{{#invoke:Register table|row|23:16}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | Y_OFFSET[7:0]
{{#invoke:Register table|row|15:8}}
| U-0 || U-0 || U-0 || U-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| — || — || — || — || colspan="4" | Y_SCALE[11:8]
{{#invoke:Register table|row|7:0}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | Y_SCALE[7:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-28 | Undefined | Initialized to <code>0</code>
| 27-26 | unused | Holds state, but ignored during display. Erroneously thought to be two msbits of the offset.
| 25-16 | Y_OFFSET[9:0] | Vertical subpixel offset ([[#Fixed-Point Format|0.10 format]])
| 15-12 | Undefined | Initialized to <code>0</code>
| 11-0 | Y_SCALE[11:0] | 1/vertical scale up factor (2.10 format)
}}
'''Extra Details:'''
: The VI keeps an internal "accumulated vertical offset" register. This register is initialized with Y_OFFSET sometimes at the beginning of the frame, and then Y_SCALE is added to it every scanline. The integer part of this internal register is then used as Y position to fetch the framebuffer.
: It is possible to change VI_Y_SCALE mid-frame, during horizontal blank. Notice though that the internal register is not reset in any way, and will keep accumulating with the new Y_SCALE value. This also means that mid-frame changes to Y_OFFSET will be ignored.

===== Erratum =====
* If Y_SCALE exceeds 0xC00, it instead behaves like a glitchy variation of 3*(0x1000-Y_SCALE)

==== <span style="display:none;">0x0440 0038 - VI_TEST_ADDR ====
----
{{#invoke:Register table|head|550px|VI_TEST_ADDR <code>0x0440 0038</code>}}
{{#invoke:Register table|row|31:24}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|23:16}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|15:8}}
| U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0 || U-0
|-
| — || — || — || — || — || — || — || —
{{#invoke:Register table|row|7:0}}
| U-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| — || colspan="7" | TEST_ADDR[6:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-7 | Undefined | Initialized to <code>0</code>
| 6-0 | TEST_ADDR[6:0] | Sets the line buffer word address at which VI_STAGED_DATA will read/write data.
}}
==== <span style="display:none;">0x0440 003C - VI_STAGED_DATA ====
----
{{#invoke:Register table|head|550px|VI_STAGED_DATA <code>0x0440 003C</code>}}
{{#invoke:Register table|row|31:24}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | STAGED_DATA[31:24]
{{#invoke:Register table|row|23:16}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | STAGED_DATA[23:16]
{{#invoke:Register table|row|15:8}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | STAGED_DATA[15:8]
{{#invoke:Register table|row|7:0}}
| RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0 || RW-0
|-
| colspan="8" | STAGED_DATA[7:0]
{{#invoke:Register table|foot}}
{{#invoke:Register table|definitions
| 31-0 | STAGED_DATA[31:0] | Reads from this register returns 32 bits of line buffer data at the address specified in VI_TEST_ADDR. Writes to this register emplace 32 bits of data into the line buffer at the address specified in VI_TEST_ADDR. Usage requires TEST_MODE to be set in VI_CTRL.
}}

= Fixed-Point Format =

[[wikipedia:Fixed-point_arithmetic|Fixed-point]] is a method of representing decimal numbers.
Unlike floating-point numbers, fixed-point numbers allocate a specific number of bits for the integer (X) and
fractional (Y) parts of the number, denoted as "X.Y format" (similar to [[wikipedia:Q_(number_format)|Q-notation]]).
In this format, a certain number of bits are dedicated to the integer part, while the
remaining bits represent the fractional part. For instance, some VI registers employ
the 2.10 format, where two bits are used for the integer part and ten bits are
allocated for the fractional part, resulting in a total of twelve bits.

Here are examples of decimals represented in 2.10 format:

[[File:2.10 fixed point examples.svg|none|none|alt=1 == 01 0000000000 (0x400); 0.25 == 00 0100000000 (0x100); 0.125 == 00 0010000000 (0x80)]]

Note that not all decimals can be represented and must be approximated.
For example, in 2.10 format the decimal 3.14 is approximated as 3.1416015625,
or `11 0010010001`. Here's an example of how to convert from the binary to decimal:

The integer part is given by adding powers of two, starting at zero and going right to left:

[[File:2.10 fixed point example 1.svg|none|none|alt=Binary: 11 -> Value: 1 × 2¹ + 1 × 2⁰ = 3]]

The fractional part is given by adding the inverse of powers of two, staring at one and going left to right:

[[File:2.10 fixed point example 2.svg|none|none|alt=Binary: 0010010001 -> Value: (0/2¹) + (0/2²) + (1/2³) + (0/2⁴) + (0/2⁵) + (1/2⁶) + (0/2⁷) + (0/2⁸) + (0/2⁹) + (1/2¹⁰)]]



= How to use this information =
=== Interlace Mode ===
The NTSC (and PAL) standard support interlace mode which is commonly associated with high resolution, but it can be used for more than that.

* High Resolution Mode
* Improve the visible detail of the image
* 60 frames per second in low resolution

==== High Resolution Mode ====
High resolution mode supports up to 480 lines (NTSC) while low resolution is 240 lines (NTSC). The Image doesn't magically grow or shrink because first the even lines are drawn on the screen, then it goes back to the top and draws the odd lines. If your game only draws the even lines then on a larger display you may have the image scanlines with smaller black lines visible between them. 

In order to implement this feature it requires the VI_V_START_REG to be modified on every VI Interrupt, so that it outputs even lines then odd lines as needed. 

NTSC Alternates between: 0x002301fd and 0x002501ff

PAL Alternates between: 0x005f0239 and 0x005d0237

Once this is explained I believe it will be fixed soon, so this is explained as an example of what the difference can be. The libdragon homebrew library doesn't actually support High Resolution Mode, because it doesn't implement this register value change. To be fair this is very easy to overlook, it works fine in every emulator and would at least look OK on a console. The difference is that emulators present the framebuffer memory as a single block of data. While the VI Interface and Video DAC see the 1 framebuffer as even lines top to bottom, then odd lines top to bottom.

Learnt from Factor 5 games(Mazamars312):

The VI_DRAM_ADDR_REG address is set to the odd or even line of the framebuffer and the VI_H_WIDTH_REG value is doubled to help skip to the next Odd or Even field line for the VI core to process. 

Once the odd or even field has been displayed the VI_DRAM_ADDR_REG is updated to the other field's address. Also the VI_Y_SCALE_REG.Subpixel is changed between fields with the values 12'h0100 and 12'h0200 to help the scaling and AA calculations (Need to find out which one is Odd and Even based as this could be game based)

The real width and height values are calculated by the following calculations

'''Width''':  C programming(float) ((VI_H_START_REG.END - VI_H_START_REG.START) * (VI_X_SCALE_REG.ScaleUp / 1024))

'''Height''':  C programming(float) (((VI_H_START_REG.END - VI_H_START_REG.START) >> 1) * (VI_X_SCALE_REG.ScaleUp / 1024))

==== Improve visible detail in low resolution ====

=== 60 Frames per second in Low Resolution mode ===
This is the easiest mode to use if your frame processing time is very low, because you simply swap the frame buffer 60 times per second inside the VI Interrupt, no other register changes are needed. 

==== Letter Boxing ====
This is a fairly common effect that is nice for cut scenes or to indicate overworld vs a level. 

VI_V_START_REG

=== Pillar Boxing ===
This feature is almost the default now since the N64 is intended for a 4:3 screen but is commonly played on 16:9 ratio screens. 

VI_H_START_REG

=== Reduce both Height and Width ===
Reducing the display size by just a few pixels also reduces the size of the world view that the player has, while usually improving performance.  Especially if the purpose of this is to improve performance I recommend doing it in increments of 8 pixels, for example either 4 or 8 pixels off each side and my increasing the size of the player status bars at either the top or bottom of the screen can also reduce the number of objects to draw on the screen.

Use the same techniques mentioned above for Letter Boxing and Pillar Boxing.

Advanced version of this is to reduce either the height or width and to increase the scaling so it still fits the screen but stretches the image out to fill the screen.

__FORCETOC__
