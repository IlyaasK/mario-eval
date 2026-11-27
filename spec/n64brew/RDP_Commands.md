<!--
  Source: https://n64brew.dev/wiki/Reality_Display_Processor/Commands
  Authors: N64brew Wiki contributors
  License: CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/)
-->


{| class="wikitable"
!  !! 0 !! 1 !! 2 !! 3 !! 4 !! 5 !! 6 !! 7
|-
| 0x00 || No Operation || No Operation || No Operation || No Operation || No Operation || No Operation || No Operation || No Operation
|-
| 0x08 || Fill Triangle || Fill Triangle (Z) || Fill Triangle (T) || Fill Triangle (TZ) || Fill Triangle (S) || Fill Triangle (SZ) || Fill Triangle (ST) || Fill Triangle (STZ)
|-
| 0x10 || No Operation || No Operation || No Operation || No Operation || No Operation || No Operation || No Operation || No Operation
|-
| 0x18 || No Operation || No Operation || No Operation || No Operation || No Operation || No Operation || No Operation || No Operation
|-
| 0x20 || No Operation || No Operation || No Operation || No Operation || Texture Rectangle || Texture Rectangle Flip || Sync Load || Sync Pipe
|-
| 0x28 || Sync Tile || Sync Full || Set Key GB || Set Key R || Set Convert || Set Scissor || Set Primitive Depth || Set Other Modes
|-
| 0x30 || Load TLUT || No Operation || Set Tile Size || Load Block || Load Tile || Set Tile || Fill Rectangle || Set Fill Color
|-
| 0x38 || Set Fog Color || Set Blend Color || Set Primitive Color || Set Environment Color || Set Combine Mode || Set Texture Image || Set Depth Image || Set Color Image
|}

=== 0x00 through 0x07, 0x10 through 0x23, 0x31 - No Operation ===
----
{| class="wikitable" style="text-align: center; white-space:nowrap;"
! colspan="17"|No Operation <code>0x00-0x07</code>,<code>0x10-0x23</code>,<code>0x31</code>
|-
| 63:48 || — || — || colspan=6| command[5:0] || — || — || — || — || — || — || — || —
|-
| 47:32 || — || — || — || — || — || — || — || — || — || — || — || — || — || — || — || —
|-
| 31:16 || — || — || — || — || — || — || — || — || — || — || — || — || — || — || — || —
|-
| 15:0 || — || — || — || — || — || — || — || — || — || — || — || — || — || — || — || —
|}
{{#invoke:Register table|definitions
| 61:56 | command[5:0] | 0x00-0x07,0x10-0x23,0x31
}}

Stalls the RDP pipeline for 1 cycle.

(TOVERIFY all of these command ids appear to behave as no-ops and take only 1 cycle to execute in testing so far, however this should be checked more extensively)

=== 0x08 through 0x0F - Fill Triangle ===
----

The Fill Triangle command varies in length depending on whether shade, texture or depth is enabled in the first word. For any of these properties that are enabled, additional words are appended to the base command words in order of shading, texturing, z-buffering.

==== Base Command ====

Every triangle type begins with a common base that describes the type, shape and other small properties of the triangle.

{| class="wikitable" style="text-align: center; white-space:nowrap;"
! colspan="18"|Fill Triangle <code>0x08</code> through <code>0x0F</code> (base)
|-
| rowspan="4"|Word 0 || 63:48 || — || — || 0 || 0 || 1 || shade || texture || zbuffer || lmajor || — || colspan=3| level[2:0] || colspan=3| tile[2:0]
|-
| 47:32 || — || — || colspan=14| yl[13:0]
|-
| 31:16 || — || — || colspan=14| ym[13:0]
|-
| 15:0 || — || — || colspan=14| yh[13:0]
|-
| rowspan="4"|Word 1 || 63:48 || — || — || — || — || colspan=12| xl.i[11:0]
|-
| 47:32 || colspan=16| xl.f[15:0]
|-
| 31:16 || — || — || colspan=14| dxldy.i[13:0]
|-
| 15:0 || colspan=16| dxldy.f[15:0]
|-
| rowspan="4"|Word 2 || 63:48 || — || — || — || — || colspan=12| xh.i[15:0]
|-
| 47:32 || colspan=16| xh.f[15:0]
|-
| 31:16 || — || — || colspan=14| dxhdy.i[15:0]
|-
| 15:0 || colspan=16| dxhdy.f[15:0]
|-
| rowspan="4"|Word 3 || 63:48 || — || — || — || — || colspan=12| xm.i[15:0]
|-
| 47:32 || colspan=16| xm.f[15:0]
|-
| 31:16 || — || — || colspan=14| dxmdy.i[15:0]
|-
| 15:0 || colspan=16| dxmdy.f[15:0]
|}
'''Word 0'''
{{#invoke:Register table|definitions
| 61:56 | command | 0x08 through 0x0F depending on features specified
| 58 | shade | If 1, command is followed by 8 words specifying shading coefficients
| 57 | texture | If 1, command is followed by 8 words specifying texturing coefficients
| 56 | zbuffer | If 1, command is followed by 2 words specifying z-buffering coefficients
| 55 | lmajor | Left-major flag, if enabled rendering occurs from left-to-right, otherwise rendering occurs from right-to-left
| 53:51 | level[2:0] | Maximum LOD level
| 50:48 | tile[2:0] | Base tile descriptor index
| 45:32 | yl[13:0] | Lowest y coordinate (largest value), rasterization ends at this height (s11.2 format)
| 29:16 | ym[13:0] | Middle y coordinate (middle value), rasterization swaps dxmdy for dxldy (s11.2 format)
| 13:0 | yh[13:0] | Highest y coordinate (highest value), rasterization begins at this height (s11.2 format)
}}
'''Word 1'''
{{#invoke:Register table|definitions
| 59:48 | xl.i[11:0] | Integer part of x coordinate on dxldy line at height ym (s11.16 format)
| 47:32 | xl.f[15:0] | Fractional part of x coordinate on dxldy line at height ym (s11.16 format)
| 29:16 | dxldy.i[13:0] | Integer part of change in x per change in y of line connecting middle and lowest vertices (s13.16 format)
| 15:0 | dxldy.f[15:0] | Fractional part of change in x per change in y of line connecting middle and lowest vertices (s13.16 format)
}}
'''Word 2'''
{{#invoke:Register table|definitions
| 59:48 | xh.i[11:0] | Integer part of x coordinate on dxhdy line at height floor(yh) (s11.16 format)
| 47:32 | xh.f[15:0] | Fractional part of x coordinate on dxhdy line at height floor(yh) (s11.16 format)
| 29:16 | dxhdy.i[13:0] | Integer part of change in x per change in y of line connecting highest and lowest vertices (s13.16 format)
| 15:0 | dxhdy.f[15:0] | Fractional part of change in x per change in y of line connecting highest and lowest vertices (s13.16 format)
}}
'''Word 3'''
{{#invoke:Register table|definitions
| 59:48 | xm.i[11:0] | Integer part of x coordinate on dxmdy line at height floor(yh) (s11.16 format)
| 47:32 | xm.f[15:0] | Fractional part of x coordinate on dxmdy line at height floor(yh) (s11.16 format)
| 29:16 | dxmdy.i[13:0] | Integer part of change in x per change in y of line connecting highest and middle vertices (s13.16 format)
| 15:0 | dxmdy.f[15:0] | Fractional part of change in x per change in y of line connecting highest and middle vertices (s13.16 format)
}}

'''Hazards'''
* In FILL mode, rendering a triangle primitive with the left-major flag unset has a high likelihood of deadlocking the RDP. (TOVERIFY: Possibly related to how crashing cases step backwards through RDRAM?)
* In FILL mode for triangles that do not crash, if the triangle primitive interacts with the scissor border the triangle will not fill correctly. The patterns this creates are not properly understood.

----

==== Optional Shading Properties ====

If the '''shade''' bit was set in the base triangle description, the above words will be followed by these 8 words describing triangle shading properties:

{| class="wikitable" style="text-align: center; white-space:nowrap;"
! colspan="18"|Fill Shaded Triangle (suffix)
|-
| rowspan="4"|Word 0 || 63:48 || - ||  - ||  - ||  - ||  - ||  - ||  - || colspan=9| r.i[8:0]
|-
| 47:32 || - ||  - ||  - ||  - ||  - ||  - ||  - || colspan=9| g.i[8:0]
|-
| 31:16 || - ||  - ||  - ||  - ||  - ||  - ||  - || colspan=9| b.i[8:0]
|-
| 15:0 || - ||  - ||  - ||  - ||  - ||  - ||  - || colspan=9| a.i[8:0]
|-
| rowspan="4"|Word 1 || 63:48 || colspan=16| drdx.i[15:0]
|-
| 47:32 || colspan=16| dgdx.i[15:0]
|-
| 31:16 || colspan=16| dbdx.i[15:0]
|-
| 15:0 || colspan=16| dadx.i[15:0]
|-
| rowspan="4"|Word 2 || 63:48 || colspan=16| r.f[15:0]
|-
| 47:32 || colspan=16| g.f[15:0]
|-
| 31:16 || colspan=16| b.f[15:0]
|-
| 15:0 || colspan=16| a.f[15:0]
|-
| rowspan="4"|Word 3 || 63:48 || colspan=16| drdx.f[15:0]
|-
| 47:32 || colspan=16| dgdx.f[15:0]
|-
| 31:16 || colspan=16| dbdx.f[15:0]
|-
| 15:0 || colspan=16| dadx.f[15:0]
|-
| rowspan="4"|Word 4 || 63:48 || colspan=16| drde.i[15:0]
|-
| 47:32 || colspan=16| dgde.i[15:0]
|-
| 31:16 || colspan=16| dbde.i[15:0]
|-
| 15:0 || colspan=16| dade.i[15:0]
|-
| rowspan="4"|Word 5 || 63:48 || colspan=16| drdy.i[15:0]
|-
| 47:32 || colspan=16| dgdy.i[15:0]
|-
| 31:16 || colspan=16| dbdy.i[15:0]
|-
| 15:0 || colspan=16| dady.i[15:0]
|-
| rowspan="4"|Word 6 || 63:48 || colspan=16| drde.f[15:0]
|-
| 47:32 || colspan=16| dgde.f[15:0]
|-
| 31:16 || colspan=16| dbde.f[15:0]
|-
| 15:0 || colspan=16| dade.f[15:0]
|-
| rowspan="4"|Word 7 || 63:48 || colspan=16| drdy.f[15:0]
|-
| 47:32 || colspan=16| dgdy.f[15:0]
|-
| 31:16 || colspan=16| dbdy.f[15:0]
|-
| 15:0 || colspan=16| dady.f[15:0]
|}
'''Word 0'''
{{#invoke:Register table|definitions
| 56:48 | r.i[8:0] | Integer part of red channel shade color at '''(xh, floor(yh))''' (s8.16 format)
| 40:32 | g.i[8:0] | Integer part of green channel shade color at '''(xh, floor(yh))''' (s8.16 format)
| 24:16 | b.i[8:0] | Integer part of blue channel shade color at '''(xh, floor(yh))''' (s8.16 format)
| 8:0 | a.i[8:0] | Integer part of alpha channel shade color at '''(xh, floor(yh))''' (s8.16 format)
}}
'''Word 1'''
{{#invoke:Register table|definitions
| 63:48 | drdx.i[15:0] | Integer part of change in red channel shade color horizontally along a scanline (s15.16 format)
| 47:32 | dgdx.i[15:0] | Integer part of change in green channel shade color horizontally along a scanline (s15.16 format)
| 31:16 | dbdx.i[15:0] | Integer part of change in blue channel shade color horizontally along a scanline (s15.16 format)
| 15:0 | dadx.i[15:0] | Integer part of change in alpha channel shade color horizontally along a scanline (s15.16 format)
}}
'''Word 2'''
{{#invoke:Register table|definitions
| 63:48 | r.f[15:0] | Fractional part of red channel shade color at '''(xh, floor(yh))''' (s8.16 format)
| 47:32 | g.f[15:0] | Fractional part of green channel shade color at '''(xh, floor(yh))''' (s8.16 format)
| 31:16 | b.f[15:0] | Fractional part of blue channel shade color at '''(xh, floor(yh))''' (s8.16 format)
| 15:0 | a.f[15:0] | Fractional part of alpha channel shade color at '''(xh, floor(yh))''' (s8.16 format)
}}
'''Word 3'''
{{#invoke:Register table|definitions
| 63:48 | drdx.f[15:0] | Fractional part of change in red channel shade color horizontally along a scanline (s15.16 format)
| 47:32 | dgdx.f[15:0] | Fractional part of change in green channel shade color horizontally along a scanline (s15.16 format)
| 31:16 | dbdx.f[15:0] | Fractional part of change in blue channel shade color horizontally along a scanline (s15.16 format)
| 15:0 | dadx.f[15:0] | Fractional part of change in alpha channel shade color horizontally along a scanline (s15.16 format)
}}
'''Word 4'''
{{#invoke:Register table|definitions
| 63:48 | drde.i[15:0] | Integer part of change in red channel shade color along the major edge (s15.16 format)
| 47:32 | dgde.i[15:0] | Integer part of change in green channel shade color along the major edge (s15.16 format)
| 31:16 | dbde.i[15:0] | Integer part of change in blue channel shade color along the major edge (s15.16 format)
| 15:0 | dade.i[15:0] | Integer part of change in alpha channel shade color along the major edge (s15.16 format)
}}
'''Word 5'''
{{#invoke:Register table|definitions
| 63:48 | drdy.i[15:0] | Integer part of change in red channel shade color for each scanline (s15.16 format)
| 47:32 | dgdy.i[15:0] | Integer part of change in green channel shade color for each scanline (s15.16 format)
| 31:16 | dbdy.i[15:0] | Integer part of change in blue channel shade color for each scanline (s15.16 format)
| 15:0 | dady.i[15:0] | Integer part of change in alpha channel shade color for each scanline (s15.16 format)
}}
'''Word 6'''
{{#invoke:Register table|definitions
| 63:48 | drde.f[15:0] | Fractional part of change in red channel shade color along the major edge (s15.16 format)
| 47:32 | dgde.f[15:0] | Fractional part of change in green channel shade color along the major edge (s15.16 format)
| 31:16 | dbde.f[15:0] | Fractional part of change in blue channel shade color along the major edge (s15.16 format)
| 15:0 | dade.f[15:0] | Fractional part of change in alpha channel shade color along the major edge (s15.16 format)
}}
'''Word 7'''
{{#invoke:Register table|definitions
| 63:48 | drdy.f[15:0] | Fractional part of change in red channel shade color for each scanline (s15.16 format)
| 47:32 | dgdy.f[15:0] | Fractional part of change in green channel shade color for each scanline (s15.16 format)
| 31:16 | dbdy.f[15:0] | Fractional part of change in blue channel shade color for each scanline (s15.16 format)
| 15:0 | dady.f[15:0] | Fractional part of change in alpha channel shade color for each scanline (s15.16 format)
}}

----

==== Optional Texturing Properties ====

If the '''texture''' bit was set in the base triangle description, the above words will be followed by these 8 words describing triangle texturing properties:

{| class="wikitable" style="text-align: center; white-space:nowrap;"
! colspan="18"|Fill Textured Triangle (suffix)
|-
| rowspan="4"|Word 0 || 63:48 || colspan=16| s[31:16]
|-
| 47:32 || colspan=16| t[31:16]
|-
| 31:16 || colspan=16| w[31:16]
|-
| 15:0 || — || — || — || — || — || — || — || — || — || — || — || — || — || — || — || —
|-
| rowspan="4"|Word 1 || 63:48 || colspan=16| dsdx.i[15:0]
|-
| 47:32 || colspan=16| dtdx.i[15:0]
|-
| 31:16 || colspan=16| dwdx.i[15:0]
|-
| 15:0 || — || — || — || — || — || — || — || — || — || — || — || — || — || — || — || —
|-
| rowspan="4"|Word 2 || 63:48 || colspan=16| s[15:0]
|-
| 47:32 || colspan=16| t[15:0]
|-
| 31:16 || colspan=16| w[15:0]
|-
| 15:0 || — || — || — || — || — || — || — || — || — || — || — || — || — || — || — || —
|-
| rowspan="4"|Word 3 || 63:48 || colspan=16| dsdx.f[15:0]
|-
| 47:32 || colspan=16| dtdx.f[15:0]
|-
| 31:16 || colspan=16| dwdx.f[15:0]
|-
| 15:0 || — || — || — || — || — || — || — || — || — || — || — || — || — || — || — || —
|-
| rowspan="4"|Word 4 || 63:48 || colspan=16| dsde.i[15:0]
|-
| 47:32 || colspan=16| dtde.i[15:0]
|-
| 31:16 || colspan=16| dwde.i[15:0]
|-
| 15:0 || — || — || — || — || — || — || — || — || — || — || — || — || — || — || — || —
|-
| rowspan="4"|Word 5 || 63:48 || colspan=16| dsdy.i[15:0]
|-
| 47:32 || colspan=16| dtdy.i[15:0]
|-
| 31:16 || colspan=16| dwdy.i[15:0]
|-
| 15:0 || — || — || — || — || — || — || — || — || — || — || — || — || — || — || — || —
|-
| rowspan="4"|Word 6 || 63:48 || colspan=16| dsde.f[15:0]
|-
| 47:32 || colspan=16| dtde.f[15:0]
|-
| 31:16 || colspan=16| dwde.f[15:0]
|-
| 15:0 || — || — || — || — || — || — || — || — || — || — || — || — || — || — || — || —
|-
| rowspan="4"|Word 7 || 63:48 || colspan=16| dsdy.f[15:0]
|-
| 47:32 || colspan=16| dtdy.f[15:0]
|-
| 31:16 || colspan=16| dwdy.f[15:0]
|-
| 15:0 || — || — || — || — || — || — || — || — || — || — || — || — || — || — || — || —
|}
'''Word 0'''
{{#invoke:Register table|definitions
| 63:48 | s[31:16] | s10.5 fixed-point part of s10.21 s-axis texture coordinate at '''(xh, floor(yh))'''
| 47:32 | t[31:16] | s10.5 fixed-point part of s10.21 t-axis texture coordinate at '''(xh, floor(yh))'''
| 31:16 | w[31:16] | s10.5 fixed-point part of s10.21 perspective scale at '''(xh, floor(yh))'''
}}
'''Word 1'''
{{#invoke:Register table|definitions
| 63:48 | dsdx.i[15:0] | Integer part of change in s-axis texture coordinate horizontally along a scanline
| 47:32 | dtdx.i[15:0] | Integer part of change in t-axis texture coordinate horizontally along a scanline
| 31:16 | dwdx.i[15:0] | Integer part of change in perspective scale horizontally along a scanline
}}
'''Word 2'''
{{#invoke:Register table|definitions
| 63:48 | s[15:0] | Least significant fractional part of s10.21 s-axis texture coordinate at '''(xh, floor(yh))'''
| 47:32 | t[15:0] | Least significant fractional part of s10.21 t-axis texture coordinate at '''(xh, floor(yh))'''
| 31:16 | w[15:0] | Least significant fractional part of s10.21 perspective scale at '''(xh, floor(yh))'''
}}
'''Word 3'''
{{#invoke:Register table|definitions
| 63:48 | dsdx.f[15:0] | Fractional part of change in s-axis texture coordinate horizontally along a scanline
| 47:32 | dtdx.f[15:0] | Fractional part of change in t-axis texture coordinate horizontally along a scanline
| 31:16 | dwdx.f[15:0] | Fractional part of change in perspective scale horizontally along a scanline
}}
'''Word 4'''
{{#invoke:Register table|definitions
| 63:48 | dsde.i[15:0] | Integer part of change in s-axis texture coordinate along the major edge
| 47:32 | dtde.i[15:0] | Integer part of change in t-axis texture coordinate along the major edge
| 31:16 | dwde.i[15:0] | Integer part of change in perspective scale along the major edge
}}
'''Word 5'''
{{#invoke:Register table|definitions
| 63:48 | dsdy.i[15:0] | Integer part of change in s-axis texture coordinate for each scanline
| 47:32 | dtdy.i[15:0] | Integer part of change in t-axis texture coordinate for each scanline
| 31:16 | dwdy.i[15:0] | Integer part of change in perspective scale for each scanline
}}
'''Word 6'''
{{#invoke:Register table|definitions
| 63:48 | dsde.f[15:0] | Fractional part of change in s-axis texture coordinate along the major edge
| 47:32 | dtde.f[15:0] | Fractional part of change in t-axis texture coordinate along the major edge
| 31:16 | dwde.f[15:0] | Fractional part of change in perspective scale along the major edge
}}
'''Word 7'''
{{#invoke:Register table|definitions
| 63:48 | dsdy.f[15:0] | Fractional part of change in s-axis texture coordinate for each scanline
| 47:32 | dtdy.f[15:0] | Fractional part of change in t-axis texture coordinate for each scanline
| 31:16 | dwdy.f[15:0] | Fractional part of change in perspective scale for each scanline
}}

'''Note''' that the number formats for the initial (s,t,w) values differ from the formats of the initial (r,g,b,a,z) values, the radix point is moved an additional 10 places to the left.

----

==== Optional Depth Properties ====

If the '''zbuffer''' bit was set in the base triangle description, the above words will be followed by these 2 words describing triangle depth properties:

{| class="wikitable" style="text-align: center; white-space:nowrap;"
! colspan="18"| Fill Z-Buffered Triangle (suffix)
|-
| rowspan="4"|Word 0 || 63:48 || colspan=16| z.i[15:0]
|-
| 47:32 || colspan=16| z.f[15:0]
|-
| 31:16 || colspan=16| dzdx.i[15:0]
|-
| 15:0 || colspan=16| dzdx.f[15:0]
|-
| rowspan="4"|Word 1 || 63:48 || colspan=16| dzde.i[15:0]
|-
| 47:32 || colspan=16| dzde.f[15:0]
|-
| 31:16 || colspan=16| dzdy.i[15:0]
|-
| 15:0 || colspan=16| dzdy.f[15:0]
|}
'''Word 0'''
{{#invoke:Register table|definitions
| 63:48 | z.i[15:0] | Integer part of depth at '''(xh, floor(yh))'''
| 47:32 | z.f[15:0] | Fractional part of depth at '''(xh, floor(yh))'''
| 31:16 | dzdx.i[15:0] | Integer part of change in depth horizontally along a scanline
| 15:0 | dzdx.f[15:0] | Fractional part of change in depth horizontally along a scanline
}}
'''Word 1'''
{{#invoke:Register table|definitions
| 63:48 | dzde.i[15:0] | Integer part of change in depth along the major edge
| 47:32 | dzde.f[15:0] | Fractional part of change in depth along the major edge
| 31:16 | dzdy.i[15:0] | Integer part of change in depth for each scanline
| 15:0 | dzdy.f[15:0] | Fractional part of change in depth for each scanline
}}

=== 0x24 and 0x25 - Texture Rectangle ===
----
{| class="wikitable" style="text-align: center; white-space:nowrap;"
! colspan="18"|Texture Rectangle <code>0x24</code> and Texture Rectangle Flip <code>0x25</code>
|-
| rowspan="4"|Word 0 || 63:48 || — || — || colspan=6| command[5:0] = 0x24 or 0x25 || colspan=8| lrx[11:4]
|-
| 47:32 || colspan=4| lrx[3:0] || colspan=12| lry[11:0]
|-
| 31:16 || — || — || — || — || — || colspan=3| tile[2:0] || colspan=8| ulx[11:4]
|-
| 15:0 || colspan=4| ulx[3:0] || colspan=12| uly[11:0]
|-
| rowspan="4"|Word 1 || 63:48 || colspan=16| s[15:0]
|-
| 47:32 || colspan=16| t[15:0]
|-
| 31:16 || colspan=16| dsdx[15:0]
|-
| 15:0 || colspan=16| dtdy[15:0]
|}

'''Word 0'''
{{#invoke:Register table|definitions
| 61:56 | command[5:0] | 0x24 (Texture_Rectangle) or 0x25 (Texture_Rectangle_Flip)
| 55:44 | lrx[11:0] | Lower-right x screen coordinate (u10.2 format)
| 43:32 | lry[11:0] | Lower-right y screen coordinate (u10.2 format)
| 26:24 | tile[2:0] | Tile descriptor index
| 23:12 | ulx[11:0] | Upper-left x screen coordinate (u10.2 format)
| 11:0 | uly[11:0] | Upper-left y screen coordinate (u10.2 format)
}}
'''Word 1'''
{{#invoke:Register table|definitions
| 63:48 | s[15:0] | Upper-left s coordinate (s10.5 format)
| 47:32 | t[15:0] | Upper-left t coordinate (s10.5 format)
| 31:16 | dsdx[15:0] | Change in s per x (s5.10 format)
| 15:0 | dtdy[15:0] | Change in t per y (s5.10 format)
}}

Renders a textured rectangle between upper-left coordinate '''(ulx,uly)''' and lower-right coordinate '''(lrx,lry)''', sampling texels using the tile descriptor indexed by '''tile'''. The coordinates '''(s,t)''' are the texture coordinates for the pixel at '''(ulx,uly)''', the derivatives '''dsdx''' and '''dtdy''' are added to these initial coordinates to determine the texture coordinates for every other pixel.

The screen coordinates are subpixel precise, integer values correspond to single pixels. In COPY and FILL mode the fractional bits are ignored and the lower-right bounds are inclusive, while in 1-Cycle and 2-Cycle modes the lower-right bounds are exclusive.

In COPY mode, since several pixels are written per cycle the '''dsdx''' parameter must account for this. It should be set such that it steps 64-bits worth of texels at a time, for example for a 16-bit color image it should be set to 4.0(s10.5) so that the s coordinate is incremented by 4 pixels (64 bits).

In FILL mode this behaves identically to '''Fill Rectangle''', the texturing properties are ignored.

Internally, this command is equivalent to a left-major triangle where <code>dxhdy = dxmdy = dxldy = 0, yl = ym = lry, yh = uly, xl = xm = lrx, xh = ulx</code>

'''Hazards'''
* In 1-Cycle and 2-Cycle mode using attributes such as shade color and per-pixel depth may be ill-defined. (TOVERIFY: It's either always 0 or uses the last value from previous primitives, check which)

=== 0x26 - Sync Load ===
----
{| class="wikitable" style="text-align: center; white-space:nowrap;"
! colspan="17"|Sync Load <code>0x26</code>
|-
| 63:48 || — || — || colspan=6| command = 0x26[5:0] || — || — || — || — || — || — || — || —
|-
| 47:32 || — || — || — || — || — || — || — || — || — || — || — || — || — || — || — || —
|-
| 31:16 || — || — || — || — || — || — || — || — || — || — || — || — || — || — || — || —
|-
| 15:0 || — || — || — || — || — || — || — || — || — || — || — || — || — || — || — || —
|}
{{#invoke:Register table|definitions
| 61:56 | command[5:0] | 0x26
}}

Stalls the RDP pipeline for exactly 25 GCLK cycles. This guarantees that the loading pipeline will be available for use following any prior operation.

The stall is always 25 cycles and does not wait on any particular internal signal(s), if a Sync Load is queued when it is not needed it simply wastes the full length of time.

=== 0x27 - Sync Pipe ===
----
{| class="wikitable" style="text-align: center; white-space:nowrap;"
! colspan="17"|Sync Pipe <code>0x27</code>
|-
| 63:48 || — || — || colspan=6| command = 0x27[5:0] || — || — || — || — || — || — || — || —
|-
| 47:32 || — || — || — || — || — || — || — || — || — || — || — || — || — || — || — || —
|-
| 31:16 || — || — || — || — || — || — || — || — || — || — || — || — || — || — || — || —
|-
| 15:0 || — || — || — || — || — || — || — || — || — || — || — || — || — || — || — || —
|}
{{#invoke:Register table|definitions
| 61:56 | command[5:0] | 0x27
}}

Stalls the RDP pipeline for exactly 50 GCLK cycles. This guarantees that any preceding primitives will be fully rendered and it is safe to modify rendering attributes such as color registers, othermodes and combine mode.

The stall is always 50 cycles and does not wait on any particular internal signal(s), if a Sync Pipe is queued when it is not needed it simply wastes the full length of time.

(TOVERIFY/Speculation: There is no known attribute that takes more than 33 cycles to sync. Can a tile sync account for all attribute changes?)

=== 0x28 - Sync Tile ===
----
{| class="wikitable" style="text-align: center; white-space:nowrap;"
! colspan="17"|Sync Tile <code>0x28</code>
|-
| 63:48 || — || — || colspan=6| command = 0x28[5:0] || — || — || — || — || — || — || — || —
|-
| 47:32 || — || — || — || — || — || — || — || — || — || — || — || — || — || — || — || —
|-
| 31:16 || — || — || — || — || — || — || — || — || — || — || — || — || — || — || — || —
|-
| 15:0 || — || — || — || — || — || — || — || — || — || — || — || — || — || — || — || —
|}
{{#invoke:Register table|definitions
| 61:56 | command[5:0] | 0x28
}}

Stalls the RDP pipeline for exactly 33 GCLK cycles. This guarantees that any preceding primitives will have finished using tile information and that it is now safe to modify tile descriptors without affecting prior primitives.

The stall is always 33 cycles and does not wait on any particular internal signal(s), if a Sync Tile is queued when it is not needed it simply wastes the full length of time.

=== 0x29 - Sync Full ===
----
{| class="wikitable" style="text-align: center; white-space:nowrap;"
! colspan="17"|Sync Full <code>0x29</code>
|-
| 63:48 || — || — || colspan=6| command = 0x29[5:0] || — || — || — || — || — || — || — || —
|-
| 47:32 || — || — || — || — || — || — || — || — || — || — || — || — || — || — || — || —
|-
| 31:16 || — || — || — || — || — || — || — || — || — || — || — || — || — || — || — || —
|-
| 15:0 || — || — || — || — || — || — || — || — || — || — || — || — || — || — || — || —
|}
{{#invoke:Register table|definitions
| 61:56 | command[5:0] | 0x29
}}

Waits for all currently staged pipeline and memory operations to complete before halting the RDP pipeline counter and raising the DP interrupt in the [[MIPS Interface]].

'''Hazards'''
* Ensure this is the final command consumed before hitting DP_END, otherwise the RDP may hang.
* Ensure no other commands are sent to RDP (via DP_START/DP_END) while a Sync Full is in progress, otherwise the RDP may hang.

=== 0x2A - Set Key GB ===
----
{| class="wikitable" style="text-align: center; white-space:nowrap;"
! colspan="17"|Set Key GB <code>0x2a</code>
|-
| 63:48 || — || — || colspan=6| command = 0x2a[5:0] || colspan=8| width_G[11:4]
|-
| 47:32 || colspan=4| width_G[3:0] || colspan=12| width_B[11:0]
|-
| 31:16 || colspan=8| center_G[7:0] || colspan=8| scale_G[7:0]
|-
| 15:0 || colspan=8| center_B[7:0] || colspan=8| scale_B[7:0]
|}
{{#invoke:Register table|definitions
| 61:56 | command[5:0] | 0x2a
| 55:44 | width_G[11:0] | Keying window half-width for green channel (4.8 format)
| 43:32 | width_B[11:0] | Keying window half-width for blue channel (4.8 format)
| 31:24 | center_G[7:0] | Center Color Combiner input for green channel
| 23:16 | scale_G[7:0] | Scale Color Combiner input for green channel
| 15:8 | center_B[7:0] | Center Color Combiner input for blue channel
| 7:0 | scale_B[7:0] | Scale Color Combiner input for blue channel
}}

Sets chroma Key parameters for the green and blue color channels.

Key width is used exclusively in the chroma key pipeline stage following the Color Combiner (if enabled in othermodes)

<math>\mathrm{key\_alpha} = \mathrm{clamp}(-\mathrm{abs}(\mathrm{Combined}) + \mathrm{Width}, 0.0, 1.0)</math>

Key center and scale are Color Combiner inputs, the expectation is that the Color Combiner is configured to <math>(X - \mathrm{Center}) \cdot \mathrm{Scale}</math> when chroma keying, where <math>X</math> is any color source. If not chroma keying, these may be used as general-purpose Color Combiner inputs.

=== 0x2B - Set Key R ===
----
{| class="wikitable" style="text-align: center; white-space:nowrap;"
! colspan="17"|Set Key R <code>0x2b</code>
|-
| 63:48 || — || — || colspan=6| command = 0x2b[5:0] || — || — || — || — || — || — || — || —
|-
| 47:32 || — || — || — || — || — || — || — || — || — || — || — || — || — || — || — || —
|-
| 31:16 || — || — || — || — || colspan=12| width_R[11:0]
|-
| 15:0 || colspan=8| center_R[7:0] || colspan=8| scale_R[7:0]
|}
{{#invoke:Register table|definitions
| 61:56 | command[5:0] | 0x2b
| 27:16 | width_R[11:0] | Keying window half-width for red channel (4.8 format)
| 15:8 | center_R[7:0] | Center Color Combiner input for red channel
| 7:0 | scale_R[7:0] | Scale Color Combiner input for red channel
}}

Sets Chroma Key parameters for the red color channel. See '''Set Key GB''' for discussion.

=== 0x2C - Set Convert ===
----
{| class="wikitable" style="text-align: center; white-space:nowrap;"
! colspan="17"|Set Convert <code>0x2c</code>
|-
| 63:48 || — || — || colspan=6| command = 0x2c[5:0] || — || — || colspan=6| K0[8:3]
|-
| 47:32 || colspan=3| K0[2:0] || colspan=9| K1[8:0] || colspan=4| K2[8:5]
|-
| 31:16 || colspan=5| K2[4:0] || colspan=9| K3[8:0] || colspan=2| K4[8:7]
|-
| 15:0 || colspan=7| K4[6:0] || colspan=9| K5[8:0]
|}
{{#invoke:Register table|definitions
| 61:56 | command[5:0] | 0x2c
| 53:45 | K0[8:0] | Color conversion constant K0
| 44:36 | K1[8:0] | Color conversion constant K1
| 35:27 | K2[8:0] | Color conversion constant K2
| 26:18 | K3[8:0] | Color conversion constant K3
| 17:9 | K4[8:0] | Color conversion constant K4
| 8:0 | K5[8:0] | Color conversion constant K5
}}

Sets colorspace conversion coefficients intended for YUV -> RGB conversion.

K0 through K3 are used in the Texture Filter color conversion step:

<math>
\begin{pmatrix}
    R \\
    G \\
    B \\
    A \\
\end{pmatrix}
=
\begin{pmatrix}
    1 & 0   & K_0 \\
    1 & K_1 & K_2 \\
    1 & K_3 & 0   \\
    1 & 0   & 0   \\
\end{pmatrix}
\begin{pmatrix}
    Y \\
    U \\
    V \\
\end{pmatrix}
</math>

K4 and K5 are made available as Color Combiner inputs, with the intention that the CC complete the colorspace conversion process after receiving values from the Texture Filter.

K4 and K5 may also simply be used as additional general-purpose CC inputs.

=== 0x2D - Set Scissor ===
----
{| class="wikitable" style="text-align: center; white-space:nowrap;"
! colspan="17"|Set Scissor <code>0x2d</code>
|-
| 63:48 || — || — || colspan=6| command = 0x2d[5:0] || colspan=8| upper_left.x[11:4]
|-
| 47:32 || colspan=4| upper_left.x[3:0] || colspan=12| upper_left.y[11:0]
|-
| 31:16 || — || — || — || — || — || — || field || odd || colspan=8| lower_right.x[11:4]
|-
| 15:0 || colspan=4| scissor.x.lo[3:0] || colspan=12| lower_right.y[11:0]
|}
{{#invoke:Register table|definitions
| 61:56 | command[5:0] | 0x2d
| 55:44 | upper_left.x[11:0] | Upper left x coordinate (u10.2 format)
| 43:32 | upper_left.y[11:0] | Upper left y coordinate (u10.2 format)
| 25 | field | Whether to perform interlaced rendering, only even or odd lines will be processed
| 24 | odd | Whether to keep even (0) or odd (1) lines when interlaced rendering is enabled
| 23:12 | lower_right.x[11:0] | Lower right x coordinate (u10.2 format)
| 11:0 | lower_right.y[11:0] | Lower right y coordinate (u10.2 format)
}}

Sets the scissor region, pixels that are outside of this region will not be processed in the pixel pipeline and will not be written to memory. Note that only the scissor determines this, the color image width has no effect. Typically the scissor width should not be larger than the color image width.

The RDP is capable of efficiently rejecting pixels that lie outside the left, right and lower scissor boundaries at no cost in time. The same cannot be said of pixels lying above the scissor region: for every line for which a primitive extends above the scissor region the RDP spends one cycle advancing each line, since it must update the attribute start values for each line.

'''Hazards'''
* The scissor region is '''inclusive''' on the right edge and '''exclusive''' on the lower edge in FILL and COPY modes, while it is '''exclusive''' on both the lower and right edges in 1-Cycle and 2-Cycle modes.
* The scissor region must be configured before rendering anything. There is no way to disable the scissor, if it is not configured it will use whatever configuration was last in the registers.
* In COPY mode, upper_left.x should be 0 (TOVERIFY Is this always true? It appears to be an unavoidable crash, but needs further investigation)
* In COPY mode, lower_right.x should be a multiple of 4 pixels (-1) to prevent possible memory corruption
* In FILL mode, upper_left.x and lower_right.x should be multiples of 4 pixels (-1 for lower_right.x) to prevent possible memory corruption
* FILL mode triangles interact bizarrely with the scissor bounds, avoid drawing such triangles that extend off-screen (TODO understand this better)
* In FILL mode sometimes scissor works at the level of individual pixels while sometimes it only works at 4-pixel boundaries. (TODO understand this better, probably to do with memory alignment)

=== 0x2E - Set Primitive Depth ===
----
{| class="wikitable" style="text-align: center; white-space:nowrap;"
! colspan="17"|Set Primitive Depth <code>0x2e</code>
|-
| 63:48 || — || — || colspan=6| command = 0x2e[5:0] || — || — || — || — || — || — || — || —
|-
| 47:32 || — || — || — || — || — || — || — || — || — || — || — || — || — || — || — || —
|-
| 31:16 || colspan=16| z[15:0]
|-
| 15:0 || colspan=16| dz[15:0]
|}
{{#invoke:Register table|definitions
| 61:56 | command[5:0] | 0x2e
| 31:16 | z[15:0] | Primitive depth value
| 15:0 | dz[15:0] | Primitive dz value
}}

Sets the primitive depth registers to the provided values. Primitive depth may be selected for depth compare instead of using per-pixel depth in the othermodes configuration. This is the only way to set a depth value for rectangle commands.

When used, the primitive depth value is taken to be the integer part of the s15.3 fixed-point z value, the fractional bits will be zero. Notably, due to not having control over the fractional bits it is impossible to configure a primitive depth value that writes the maximum possible depth value into the z-buffer.

Unlike the majority of other attribute-setters, primitive depth operates correctly even in the absence of pipeline synchronizations. Primitive depth may be changed between primitive rendering without corrupting prior primitives.

'''Hazards'''
* The dz value provided should be a power of 2 to ensure correct operation. RDP hardware uses a cheap integer log2 algorithm for computing log2(dz) that is only guaranteed to produce correct results when the input is a power of 2. Notably, the value 0xFFFF happens to work correctly.

=== 0x2F - Set Other Modes ===
----
{| class="wikitable" style="text-align: center; white-space:nowrap;"
! colspan="17"|Set Other Modes <code>0x2f</code>
|-
| 63:48 || — || — || colspan=6| command = 0x2f[5:0] || atomic_prim || - || colspan=2| cycle_type[1:0] || persp_tex_en || detail_tex_en || sharpen_tex_en || tex_lod_en
|-
| 47:32 || tlut_en || tlut_type || sample_type || mid_texel || bi_lerp_0 || bi_lerp_1 || convert_one || key_en || colspan=2| rgb_dither_sel[1:0] || colspan=2| alpha_dither_sel[1:0] || colspan=4| -
|-
| 31:16 || colspan=2| bl_m1a_0[1:0] || colspan=2| bl_m1a_1[1:0] || colspan=2| bl_m1b_0[1:0] || colspan=2| bl_m1b_1[1:0] || colspan=2| bl_m2a_0[1:0] || colspan=2| bl_m2a_1[1:0] || colspan=2| bl_m2b_0[1:0] || colspan=2| bl_m2b_1[1:0]
|-
| 15:0 || - || force_blend || alpha_cvg_select || cvg_x_alpha || colspan=2| z_mode[1:0] || colspan=2| cvg_dest[1:0] || color_on_cvg || image_read_en || z_update_en || z_compare_en || antialias_en || z_source_sel || dither_alpha_en || alpha_compare_en
|}
{{#invoke:Register table|definitions
| 61:56 | command[5:0] | 0x2f
| 55 | atomic_prim | Enables span buffer coherency, forces active span segments to be written to the frame buffer before reading new span segments
| 54 | - | ?
| 53:52 | cycle_type[1:0] | Determines pipeline mode. Either 1-Cycle (0), 2-Cycle (1), COPY (2), FILL (3)
| 51 | persp_tex_en | Enables perspective correction of texture coordinates
| 50 | detail_tex_en | Enables "detail texture" mode in Texture LOD
| 49 | sharpen_tex_en | Enables "sharpen texture" mode in Texture LOD
| 48 | tex_lod_en | Enables Texture Level of Detail (LOD)
| 47 | tlut_en | Enables Texture Look-Up Table (TLUT) sampling. Texels are first fetched from low TMEM that are then used to index a palette in high TMEM to find the final color values.
| 46 | tlut_type | Determines TLUT texel format. Either RGBA16 (0) or IA16 (1)
| 45 | sample_type | Determines texel sampling mode. Either point-sampled (0) or 2x2 bilinear (1)
| 44 | mid_texel | Determines bilinear filter mode. Either 3-point (0) or average mode (1)
| 43 | bi_lerp_0 | Determines texture filter mode for the first cycle. Either YUV to RGB conversion (See '''Set Convert''') (0) or bilinear filter (1)
| 42 | bi_lerp_1 | Determines texture filter mode for the second cycle. Either YUV to RGB conversion (See '''Set Convert''') (0) or bilinear filter (1)
| 41 | convert_one | Determines the input to the second texture filter stage. Either the sample from the second stage of texture sampling (0) or the result from the first texture filter cycle (1)
| 40 | key_en | Enables chroma keying following the Color Combiner stage
| 39:38 | rgb_dither_sel[1:0] | Set RGB dither mode
| 37:36 | alpha_dither_sel[1:0] | Set Alpha dither mode
| 35:32 | - | ?
| 31:30 | bl_m1a_0[1:0] | Blender input P (first cycle)
| 29:28 | bl_m1a_1[1:0] | Blender input P (second cycle)
| 27:26 | bl_m1b_0[1:0] | Blender input A (first cycle)
| 25:24 | bl_m1b_1[1:0] | Blender input A (second cycle)
| 23:22 | bl_m2a_0[1:0] | Blender input M (first cycle)
| 21:20 | bl_m2a_1[1:0] | Blender input M (second cycle)
| 19:18 | bl_m2b_0[1:0] | Blender input B (first cycle)
| 17:16 | bl_m2b_1[1:0] | Blender input B (second cycle)
| 15 | - | ?
| 14 | force_blend | Enables blending for all pixels rather than only edge pixels
| 13 | alpha_cvg_select | Use coverage (or coverage multiplied by CC alpha) for alpha input to blender rather than alpha output from CC
| 12 | cvg_x_alpha | Multiply coverage and alpha from CC (used in conjunction with alpha_cvg_sel)
| 11:10 | z_mode[1:0] | Determines z-buffer comparator mode
| 9:8 | cvg_dest[1:0] | Determines coverage output mode
| 7 | color_on_cvg | If enabled, writes the blender output only if coverage overflowed, otherwise write the 2B input verbatim
| 6 | image_read_en | Enable color image reading
| 5 | z_update_en | Enable z-buffer writing
| 4 | z_compare_en | Enable z-buffer reading and depth comparison
| 3 | antialias_en | Enable anti-aliasing, which may enable blending on edge pixels
| 2 | z_source_sel | Selects either per-pixel (0) or primitive (1) depth as depth source to compare against the z-buffer
| 1 | dither_alpha_en | Determines alpha compare threshold source. (0 blend color register alpha, 1 random)
| 0 | alpha_compare_en | Enables alpha compare, pixels below the alpha threshold (compared against CC alpha output) are not written
}}

Configures the RDP "Other Modes", a collection of global settings.

'''RGB dither modes'''

{| class="wikitable"
! Value !! Description
|-
| 0 || 4x4 Magic Square dither matrix
|-
| 1 || 4x4 Bayer dither matrix
|-
| 2 || Random noise. Note the random sample is different per color channel, grayscale images may not remain grayscale after noise dithering.
|-
| 3 || Disabled, no dithering applied
|}

The dither matrices are both 4x4 and are indexed by the (integer) screen coordinates mod 4, or bits [1:0]. If scissoring is used, the y coordinate bits [2:1] are used to index the matrix instead.

The Bayer matrix is:

<math>
\begin{pmatrix}
    0 & 4 & 1 & 5 \\
    4 & 0 & 5 & 1 \\
    3 & 7 & 2 & 6 \\
    7 & 3 & 6 & 2 \\
\end{pmatrix}
</math>

The Magic Square matrix is:

<math>
\begin{pmatrix}
    0 & 6 & 1 & 7 \\
    4 & 2 & 5 & 3 \\
    3 & 5 & 2 & 4 \\
    7 & 1 & 6 & 0 \\
\end{pmatrix}
</math>

'''Alpha dither modes'''

{| class="wikitable"
! Value !! Description
|-
| 0 || Same pattern as chosen in RGB. If RGB dither was set to noise, use magic square. If RGB dither was disabled, use bayer.
|-
| 1 || Inverse of the same pattern as chosen in RGB. Same rules as above if RGB dither was set to noise or disabled.
|-
| 2 || Random noise
|-
| 3 || Disabled, no dithering applied
|}

'''Z modes'''

{| class="wikitable"
! Value !! Description
|-
| 0 || Opaque surface mode.
|-
| 1 || Interpenetrating surface mode.
|-
| 2 || Transparent surface mode.
|-
| 3 || Decal surface mode.
|}

'''Coverage destination modes'''

{| class="wikitable"
! Value !! Description
|-
| 0 || Clamp. Sums new and old coverage, clamps to full if there is an overflow.
|-
| 1 || Wrap. Sums new and old coverage, writes this sum modulo 8.
|-
| 2 || Full. Always write full coverage.
|-
| 3 || Save. Always write old coverage, discard new coverage. Requires image_read_en, otherwise it will behave like Full.
|}

'''Blender Configuration'''

Other modes include the blender input configuration. The blender computes either

<math>p \cdot a + m \cdot b</math>

or

<math>\frac{p \cdot a + m \cdot b}{a + b}</math>

The latter is performed only when force_blend is disabled and anti-aliasing is enabled, where it is performed only on edge pixels.

'''Blender P and M Inputs'''

{| class="wikitable"
! Value !! Description
|-
| 0 || First cycle: output color from Color Combiner final stage; Second cycle: output color from first blender cycle
|-
| 1 || Memory color from framebuffer
|-
| 2 || Blend color register RGB
|-
| 3 || Fog color register RGB
|}

'''Blender A Inputs'''

{| class="wikitable"
! Value !! Description
|-
| 0 || Output alpha from Color Combiner final stage
|-
| 1 || Fog color register Alpha
|-
| 2 || Shade Alpha (interpolated per-pixel)
|-
| 3 || Fixed 0.0
|}

'''Blender B Inputs'''

{| class="wikitable"
! Value !! Description
|-
| 0 || 1.0 - A, where A is the other alpha input
|-
| 1 || Memory coverage from framebuffer
|-
| 2 || Fixed 1.0
|-
| 3 || Fixed 0.0
|}

'''Hazards'''
* This is a pipeline configuration command that requires pipeline synchronization before use, otherwise currently rendering primitives may be partially rendered using both the old other modes configuration and the new other modes configuration.
* In 1-Cycle mode only the blender's first cycle configuration is used, the second cycle configuration is ignored.
* Alpha compare in COPY mode targeting 16-bit framebuffers is only valid for RGBA5551 textures, it only considers the least-significant bit in the sampled texel for determining whether to write it.
* Blender hazards:
** If memory color was set as a blender input, '''image_read_en''' should be enabled for proper operation.
** If memory coverage was set as a blender input, '''image_read_en''' should be enabled for proper operation. If it is left disabled, memory coverage is set to full.
** If '''cvg_dest''' was set to ''Save'' (3), '''image_read_en''' should be enabled for proper operation. If it is left disabled, ''Save'' (3) will act like ''Full'' (2).
** 2-Cycle mode pipeline bug: In the first cycle of 2-cycle mode, memory color is read from the previous pixel.
** 2-Cycle mode pipeline bug: In the first cycle of 2-cycle mode, memory coverage is read from the previous pixel.
** 2-Cycle mode pipeline bug: In the second cycle of 2-cycle mode, shade alpha is read from the next pixel.
** 2-Cycle mode pipeline bug: Alpha compare uses the output of the first combiner cycle of the next pixel as the value to compare to the threshold.

=== 0x30 - Load TLUT ===
----
{| class="wikitable" style="text-align: center; white-space:nowrap;"
! colspan="17"|Load TLUT <code>0x30</code>
|-
| 63:48 || — || — || colspan=6| command = 0x30[5:0] || colspan="8" | upper_left.s[11:4]
|-
| 47:32 || colspan=4| upper_left.s[3:0] || colspan=12| upper_left.t[11:0]
|-
| 31:16 || — || — || — || — || — || colspan=3| tile[2:0] || colspan=8| lower_right.s[11:4]
|-
| 15:0 || colspan=4| lower_right.s[3:0] || colspan=12| lower_right.t[11:0]
|}
{{#invoke:Register table|definitions
| 61:56 | command[5:0] | 0x30
| 55:44 | upper_left.s[11:0] | Upper-left s coordinate (u10.2)
| 43:32 | upper_left.t[11:0] | Upper-left t coordinate (u10.2)
| 26:24 | tile[2:0] | Tile descriptor index
| 23:12 | lower_right.s[11:0] | Lower-right s coordinate (u10.2)
| 11:0 | lower_right.t[11:0] | Lower-right t coordinate (u10.2)
}}

Loads a Texture Look-Up Table (TLUT) into TMEM.

When loading with Load TLUT, every texel loaded from RDRAM is quadrupled and placed adjacently in TMEM. A 256-color TLUT therefore takes up <math>\mathrm{256} \times \mathrm{2} \times \mathrm{4} = \mathrm{0x800}</math> bytes of TMEM, which is the maximum size of a TLUT as it must fit in high TMEM. A 16-color TLUT takes up only <math>\mathrm{16} \times \mathrm{2} \times \mathrm{4} = \mathrm{0x80}</math> bytes of TMEM, 16 of these may reside in high TMEM at the same time.

Load TLUT updates the tile size for the selected tile descriptor to <code>(upper_left.s, upper_left.t, lower_right.s, lower_right.t)</code>. This is generally undesirable for rendering; ensure that, if using the same tile for subsequent rendering, the tile size is reconfigured following this command with appropriate synchronization.

Typical usage of Load TLUT may resemble <code>(uls=0, ult=0, lrs=count-1, lrt=0)</code> where <code>count</code> is the number of texels making up the TLUT, e.g. 255 for a 256-color palette.

'''Hazards'''
* To ensure data is loaded correctly the associated tile descriptor should be configured to use a 4-bit texel size, and should not be configured to use YUV or RGBA texel formats. Note however that the texture image should still be configured to use a 16-bit texel size.
* For correct sampling, the base TMEM address for a TLUT must reside in the upper half of TMEM, that is at TMEM word address 0x100 (byte address 0x800) or greater.
* For correct sampling, the base TMEM address for a TLUT must be aligned to 16 TMEM words or 128 bytes.

=== 0x32 - Set Tile Size ===
----
{| class="wikitable" style="text-align: center; white-space:nowrap;"
! colspan="17"|Set Tile Size <code>0x32</code>
|-
| 63:48 || — || — || colspan=6| command = 0x32[5:0] || colspan=8| upper_left.s[11:4]
|-
| 47:32 || colspan=4| upper_left.s[3:0] || colspan=12| upper_left.t[11:0]
|-
| 31:16 || — || — || — || — || — || colspan=3| index[2:0] || colspan=8| lower_right.s[11:4]
|-
| 15:0 || colspan=4| lower_right.s[3:0] || colspan=12| lower_right.t[11:0]
|}
{{#invoke:Register table|definitions
| 61:56 | command[5:0] | 0x32
| 55:44 | upper_left.s[11:0] | Upper-left s coordinate (u10.2 format)
| 43:32 | upper_left.t[11:0] | Upper-left t coordinate (u10.2 format)
| 26:24 | index[2:0] | Tile descriptor index
| 23:12 | lower_right.s[11:0] | Lower-right s coordinate (u10.2 format)
| 11:0 | lower_right.t[11:0] | Lower-right t coordinate (u10.2 format)
}}

Updates the tile extents for the tile descriptor specified by the index parameter.

The upper-left coordinate specifies the origin of the tile, where texture coordinates (0,0) would sample from, and sets the lower extents for clamp/mask/mirror in texture sampling.

The lower-right coordinate specifies the upper extents for clamp/mask/mirror in texture sampling.

=== 0x33 - Load Block ===
----
{| class="wikitable" style="text-align: center; white-space:nowrap;"
! colspan="17"|Load Block <code>0x33</code>
|-
| 63:48 || — || — || colspan=6| command = 0x33[5:0] || colspan=8| upper_left.s[11:4]
|-
| 47:32 || colspan=4| upper_left.s[3:0] || colspan=12| upper_left.t[11:0]
|-
| 31:16 || — || — || — || — || — || colspan=3| tile[2:0] || colspan=8| lower_right.s[11:4]
|-
| 15:0 || colspan=4| lower_right.s[3:0] || colspan=12| dxt[11:0]
|}
{{#invoke:Register table|definitions
| 61:56 | command[5:0] | 0x33
| 55:44 | upper_left.s[11:0] | Upper-left s coordinate (u12.0)
| 43:32 | upper_left.t[11:0] | Upper-left t coordinate (u12.0)
| 26:24 | tile[2:0] | Tile descriptor index
| 23:12 | lower_right.s[11:0] | Lower-right s coordinate (u12.0)
| 11:0 | dxt[11:0] | Change in x per t (u1.11)
}}

Load Block loads texels to the TMEM address specified by the selected tile descriptor from the RDRAM location pointed to by the current texture image (see '''Set Texture Image''').

Only 2048 texels of any size can be loaded at once, loads configured to read more than 2048 texels will fail resulting in nothing being written into TMEM. For 4 and 8 bit types the texture image texel size can be set to 16-bit to facilitate loading more than 2048 texels, it is not possible to use the 32-bit texel size in this way without advance preparation as 32-bit texels have a different TMEM layout. <code>lower_right.s - upper_left.s</code> determines the number of texels to load.

Load Block is the fastest way to move data from RDRAM into TMEM, however not all width/height combinations are valid. Texture lines loaded with Load Block must be a multiple of 64 bits in size, either naturally or by explicitly padding each line in RDRAM. Further, for a given width there is a maximum height based on imprecision in the dxt value. For each 64-bit TMEM word loaded with Load Block, an internal counter is incremented by dxt. This counter can be thought of as a 1.11 fixed-point value; when the counter holds a value greater than one the current word being loaded belongs to an odd-numbered line, otherwise it belongs to an even-numbered line. For texture sampling reasons odd lines must have their 32-bit words swapped when loaded from RDRAM, this is done automatically by the loading hardware hence why it tracks which lines are even or odd. However if dxt is sufficiently imprecise the counter may miss a word at the end of a line, leading to corruptions as that word will not be swapped correctly.

Like '''Load Tile''', both <code>upper_left</code> parameters offset the RDRAM base address of the data to be loaded into the tile TMEM address.

'''Hazards'''
* Load Block sets the tile size for the associated tile descriptor to (upper_left.s, upper_left.t, lower_right.s, dxt). This is generally not a useful configuration for rendering the image.
* Loads that extend past the end of TMEM will wrap back to the start.
* The texel size specified in '''Set Texture Image''' should match the texel size in the tile descriptor used for loading, otherwise operation is not guaranteed.
* Some texture image addresses may hang the RDP if an attempt is made to load from it. See '''Set Texture Image''' hazards.

=== 0x34 - Load Tile ===
----
{| class="wikitable" style="text-align: center; white-space:nowrap;"
! colspan="17"|Load Tile <code>0x34</code>
|-
| 63:48 || — || — || colspan=6| command = 0x34[5:0] || colspan=8| upper_left.s[11:4]
|-
| 47:32 || colspan=4| upper_left.s[3:0] || colspan=12| upper_left.t[11:0]
|-
| 31:16 || — || — || — || — || — || colspan=3| tile[2:0] || colspan=8| lower_right.s[11:4]
|-
| 15:0 || colspan=4| lower_right.s[3:0] || colspan=12| lower_right.t[11:0]
|}
{{#invoke:Register table|definitions
| 61:56 | command[5:0] | 0x34
| 55:44 | upper_left.s[11:0] | Upper-left s coordinate (u10.2)
| 43:32 | upper_left.t[11:0] | Upper-left t coordinate (u10.2)
| 26:24 | tile[2:0] | Tile descriptor index
| 23:12 | lower_right.s[11:0] | Lower-right s coordinate (u10.2)
| 11:0 | lower_right.t[11:0] | Lower-right t coordinate (u10.2)
}}

Load Tile loads an arbitrary rectangle of texels to the TMEM address specified by the selected tile descriptor from the RDRAM location pointed to by the current texture image (see '''Set Texture Image'''). The rectangle in RDRAM to load from is specified by the provided upper_left and lower_right coordinates and the line parameter in the tile descriptor, the RDRAM width is <code>lower_right.s - upper_left.s</code> while the TMEM width is the tile line parameter. The upper_left location in RDRAM is mapped to the tile TMEM address.

Load Tile is slower than Load Block, however it is more flexible as there is no need to explicitly pad texture lines in RDRAM to 8-byte boundaries, and there are no issues with word-swapping.

Load Tile updates the tile size for the selected tile descriptor to <code>(upper_left.s, upper_left.t, lower_right.s, lower_right.t)</code> which may be used for subsequent rendering.

'''Hazards'''
* The width configured in '''Set Texture Image''' should match the RDRAM width configured in the tile descriptor, otherwise operation is not guaranteed.
* Loads that extend past the end of TMEM will wrap back to the start.
* The texel size specified in '''Set Texture Image''' should match the texel size in the tile descriptor used for loading, otherwise operation is not guaranteed.
* Some texture image addresses may hang the RDP if an attempt is made to load from it. See '''Set Texture Image''' hazards.

=== 0x35 - Set Tile ===
----
{| class="wikitable" style="text-align: center; white-space:nowrap;"
! colspan="17"|Set Tile <code>0x35</code>
|-
| 63:48 || — || — || colspan=6| command = 0x35[5:0] || colspan=3| format[2:0] || colspan=2| size[1:0] || — || colspan=2| line[8:7]
|-
| 47:32 || colspan=7| line[6:0] || colspan=9| address[8:0]
|-
| 31:16 || — || — || — || — || — || colspan=3| index[2:0] || colspan=4| palette[3:0] || clamp_T || mirror_T || colspan=2| mask_T[3:2]
|-
| 15:0 || colspan=2| mask_T[1:0] || colspan=4| shift_T[3:0] || clamp_S || mirror_S || colspan=4| mask_S[3:0] || colspan=4| shift_S[3:0]
|}
{{#invoke:Register table|definitions
| 61:56 | command[5:0] | 0x35
| 55:53 | format[2:0] | Tile texel format
| 52:51 | size[1:0] | Tile texel size
| 49:41 | line[8:0] | Tile line length in TMEM words
| 40:32 | address[8:0] | TMEM address in TMEM words
| 26:24 | index[2:0] | Tile index
| 23:20 | palette[3:0] | Palette index
| 19 | clamp_T | Clamp enable (T-axis)
| 18 | mirror_T | Mirror enable (T-axis)
| 17:14 | mask_T[3:0] | Mask (T-axis)
| 13:10 | shift_T[3:0] | Shift (T-axis)
| 9 | clamp_S | Clamp enable (S-axis)
| 8 | mirror_S | Mirror enable (S-axis)
| 7:4 | mask_S[3:0] | Mask (S-axis)
| 3:0 | shift_S[3:0] | Shift (S-axis)
}}

Configures the tile descriptor specified by the index parameter.

The texel '''format''' parameter is selected from
{| class="wikitable"
! Format Name !! Format Value
|-
| RGBA || 0
|-
| YUV || 1
|-
| Color-Indexed (CI) || 2
|-
| Intensity-Alpha (IA) || 3
|-
| Intensity (I) || 4+
|}

The texel '''size''' parameter is selected from
{| class="wikitable"
! Bits per pixel !! Size Value
|-
| 4 || 0
|-
| 8 || 1
|-
| 16 || 2
|-
| 32 || 3
|}

Officially supported format/size combinations
{| class="wikitable" style="text-align: center; white-space:nowrap;"
!   !! RGBA !! YUV !!CI !! IA !! I
|-
| '''4''' || - || - || {{tick|color=black}} || {{tick|color=black}} || {{tick|color=black}}
|-
| '''8''' || - || - || {{tick|color=black}} || {{tick|color=black}} || {{tick|color=black}}
|-
| '''16''' || {{tick|color=black}} || {{tick|color=black}} || - || {{tick|color=black}} || -
|-
| '''32''' || {{tick|color=black}} || - || - || - || -
|}

The '''line''' parameter indicates the number of TMEM (64-bit) words in a single row of the tile. This quantity is typically calculated from the tile width in texels and texel size as <code>(width * NBITS(size) + 63) / 64</code> where <code>NBITS(size)</code> is the number of bits per texel. If a texture width is not an integral number of TMEM words, each row must be padded to begin on a new TMEM word; Load Tile performs this padding transparently when loading texture data from RDRAM into TMEM, for Load Block the data must already be padded in RDRAM.

The '''address''' is a TMEM word (64-bit) address. For example an address of 0x100 resolves to byte address 0x800, half way through TMEM.

The '''palette''' parameter is for CI4 formatted tiles, for CI formats of other sizes it is ignored altogether. It is the upper half of a TMEM address, indicating where the tile can find the associated color palette. The lower half of the TMEM address is populated by the color index in the CI4 texture data.

The '''clamp/mirror/mask/shift''' parameters for each texture coordinate axis influence how texels are sampled from the tile during texture sampling. (TODO link texture sampling article)
* '''clamp''': Enables clamping. When the tile is sampled with coordinates that fall outside the tile boundaries, the nearest texel that is within the tile bounds will be used. If disabled, coordinates are brought into the tile range by wrapping based on the mask value, which operates on powers of 2. Therefore, if a tile extent is not a power of 2 clamping should typically be used.
* '''mirror''': Enables mirroring. When oversampling the tile, flip the axis.
* '''mask''': Determines how many bits of the integer part of the texture coordinate should be considered for sampling from this tile. A mask of 0 indicates all bits should be considered.
* '''shift''': Optional shift amount for texture coordinates. Values 1-10 shift right while 11-15 shift left.
{| class="wikitable" style="text-align: center; white-space:nowrap;"
! Shift value !! Operation
|-
| 0 || N/A
|-
| 1 || >> 1
|-
| 2 || >> 2
|-
| colspan=2| ...
|-
| 10 || >> 10
|-
| 11 || << 5
|-
| 12 || << 4
|-
| 13 || << 3
|-
| 14 || << 2
|-
| 15 || << 1
|}

=== 0x36 - Fill Rectangle ===
----
{| class="wikitable" style="text-align: center; white-space:nowrap;"
! colspan="17"|Fill Rectangle <code>0x36</code>
|-
| 63:48 || — || — || colspan=6| command = 0x36[5:0] || colspan=8| lower_right.x[11:4]
|-
| 47:32 || colspan=4| lower_right.x[3:0] || colspan=12| lower_right.y[11:0]
|-
| 31:16 || — || — || — || — || — || — || — || — || colspan=8| upper_left.x[11:4]
|-
| 15:0 || colspan=4| upper_left.x[3:0] || colspan=12| upper_left.y[11:0]
|}
{{#invoke:Register table|definitions
| 61:56 | command[5:0] | 0x36
| 55:44 | lower_right.x[11:0] | Lower-right x coordinate (u10.2 format)
| 43:32 | lower_right.y[11:0] | Lower-right y coordinate (u10.2 format)
| 23:12 | upper_left.x[11:0] | Upper-left x coordinate (u10.2 format)
| 11:0 | upper_left.y[11:0] | Upper-right y coordinate (u10.2 format)
}}

Renders a solid-color rectangle.

In FILL and COPY mode, the rectangle coordinates are inclusive on the right and lower edges while in 1-Cycle and 2-Cycle mode they are exclusive.

In 1-Cycle or 2-Cycle mode, the rectangle is rendered with subpixel accuracy and can be anti-aliased if pixels are only partially covered. The color is determined by the blender output as with triangles and texture rectangles, not the fill color register.

In FILL mode, the rectangle is rendered without subpixel accuracy (upper-left coordinates are rounded down, lower-right coordinates are rounded up) and the color is determined solely by the fill color register.

Internally, this command is equivalent to a left-major triangle where <code>dxhdy = dxmdy = dxldy = 0, yl = ym = lry, yh = uly, xl = xm = lrx, xh = ulx</code>

'''Hazards'''
* In 1-Cycle and 2-Cycle mode using attributes such as shade color, texture coordinates and per-pixel depth may be ill-defined. (TOVERIFY: It's either always 0 or uses the last value from previous primitives, check which)
* In COPY mode, fill rectangle behaves like texture rectangle with all texture attributes (tile, s, t, dsdx, dtdy) set to 0. (TOVERIFY: as above, is it always 0 or is it left over values from previous primitives?)

=== 0x37 - Set Fill Color ===
----
{| class="wikitable" style="text-align: center; white-space:nowrap;"
! colspan="17"|Set Fill Color <code>0x37</code>
|-
| 63:48 || — || — || colspan=6| command = 0x37[5:0] || — || — || — || — || — || — || — || —
|-
| 47:32 || — || — || — || — || — || — || — || — || — || — || — || — || — || — || — || —
|-
| 31:16 || colspan=16| color[31:16]
|-
| 15:0 || colspan=16| color[15:0]
|}
{{#invoke:Register table|definitions
| 61:56 | command[5:0] | 0x37
| 31:0 | color[31:0] | Fill Color. Format varies based on color image pixel size, see below
}}

Sets the fill color register, the color to use when rendering primitives in FILL mode. This is the only color sampled by FILL mode as all other pipeline stages are bypassed. This color is not made available to the Color Combiner or the Blender, and Fill Rectangle outside of FILL mode does not use it.

Since FILL mode simply repeats the 32-bit value verbatim out to memory, proper usage of the color parameter will depend on the color image configuration:
* 32-bit: A single RGBA32 color occupying all 32 bits.
* 16-bit: Two RGBA16 colors occupying the upper and lower 16 bits respectively. Even pixels sample the upper half and odd pixels sample the lower half. For filling the color image with a solid color, simply let the upper and lower halves hold the same value.
* 8-bit: Four 8-bit intensity values, repeating every four pixels.
* 4-bit: N/A, crash

'''Hazards'''
* This is an attribute-setting command that requires pipeline synchronization before use, otherwise currently rendering primitives may be partially rendered using both the old fill color and the new fill color, if it was used.

=== 0x38 - Set Fog Color ===
----
{| class="wikitable" style="text-align: center; white-space:nowrap;"
! colspan="17"|Set Fog Color <code>0x38</code>
|-
| 63:48 || — || — || colspan=6| command = 0x38[5:0] || — || — || — || — || — || — || — || —
|-
| 47:32 || — || — || — || — || — || — || — || — || — || — || — || — || — || — || — || —
|-
| 31:16 || colspan=8| red[7:0] || colspan=8| green[7:0]
|-
| 15:0 || colspan=8| blue[7:0] || colspan=8| alpha[7:0]
|}
{{#invoke:Register table|definitions
| 61:56 | command[5:0] | 0x38
| 31:24 | red[7:0] | Fog Red Value
| 23:16 | green[7:0] | Fog Green Value
| 15:8 | blue[7:0] | Fog Blue Value
| 7:0 | alpha[7:0] | Fog Alpha Value
}}

Sets the "Fog" color register to the provided RGBA value. This color is accessible from the Blender as an input.

The name "Fog" reflects only one particular usage of how the color may be used, the name does not relate to any particular meaning in the hardware.

'''Hazards'''
* This is an attribute-setting command that requires pipeline synchronization before use, otherwise currently rendering primitives may be partially rendered using both the old fog color and the new fog color, if it was used.

=== 0x39 - Set Blend Color ===
----
{| class="wikitable" style="text-align: center; white-space:nowrap;"
! colspan="17"|Set Blend Color <code>0x39</code>
|-
| 63:48 || — || — || colspan=6| command = 0x39[5:0] || — || — || — || — || — || — || — || —
|-
| 47:32 || — || — || — || — || — || — || — || — || — || — || — || — || — || — || — || —
|-
| 31:16 || colspan=8| red[7:0] || colspan=8| green[7:0]
|-
| 15:0 || colspan=8| blue[7:0] || colspan=8| alpha[7:0]
|}
{{#invoke:Register table|definitions
| 61:56 | command[5:0] | 0x39
| 31:24 | red[7:0] | Blend Red Value
| 23:16 | green[7:0] | Blend Green Value
| 15:8 | blue[7:0] | Blend Blue Value
| 7:0 | alpha[7:0] | Blend Alpha Value
}}

Sets the "Blend" color register to the provided RGBA value. This color is accessible from the Blender as an input.

The name "Blend" reflects only one particular usage of how the color may be used, the name does not relate to any particular meaning in the hardware.

'''Hazards'''
* This is an attribute-setting command that requires pipeline synchronization before use, otherwise currently rendering primitives may be partially rendered using both the old blend color and the new blend color, if it was used.

=== 0x3A - Set Primitive Color ===
----
{| class="wikitable" style="text-align: center; white-space:nowrap;"
! colspan="17"|Set Primitive Color <code>0x3a</code>
|-
| 63:48 || — || — || colspan=6| command = 0x3a[5:0] || — || — || — || — || — || — || — || —
|-
| 47:32 || colspan=8| min_level[7:0] || colspan=8| prim_lod_frac[7:0]
|-
| 31:16 || colspan=8| red[7:0] || colspan=8| green[7:0]
|-
| 15:0 || colspan=8| blue[7:0] || colspan=8| alpha[7:0]
|}
{{#invoke:Register table|definitions
| 61:56 | command[5:0] | 0x3a
| 47:40 | min_level[7:0] | Minimum LOD level
| 39:32 | prim_lod_frac[7:0] | Primitive LOD Fraction Color Combiner input
| 31:24 | red[7:0] | Primitive Red Value
| 23:16 | green[7:0] | Primitive Green Value
| 15:8 | blue[7:0] | Primitive Blue Value
| 7:0 | alpha[7:0] | Primitive Alpha Value
}}

Sets the "Primitive" color register to the provided RGBA value, and some LOD parameters. The color is accessible from the Color Combiner as an input.

The name "Primitive" reflects only one particular usage of how the color may be used, the name does not relate to any particular meaning in the hardware.

'''prim_lod_frac''' is simply another Color Combiner input, despite the name it is not used by the texture LOD hardware feature. It may be used as a fixed interpolation factor.

'''min_level''' is used in the texture LOD hardware, it bounds the LOD tile selection from below. The LOD value selecting a particular tile '''N''' can be computed by

<math>L = 32 \cdot 2^{(N - T_{\mathrm{base}})}</math>

where '''T<sub>base</sub>''' is the tile number set in the triangle command. For texture rectangles this is tile 0.

If the LOD computed for a particular pixel during texture sampling is less than the minimum LOD level, tile 0 is used. Detail and sharpen modes may still apply. (TODO link to more detailed Texture LOD article)

Unlike the majority of other attribute-setters, primitive color operates correctly even in the absence of pipeline synchronizations. The primitive color may be changed between primitive rendering without corrupting prior primitives.

=== 0x3B - Set Environment Color ===
----
{| class="wikitable" style="text-align: center; white-space:nowrap;"
! colspan="17"|Set Environment Color <code>0x3b</code>
|-
| 63:48 || — || — || colspan=6| command = 0x3b[5:0] || — || — || — || — || — || — || — || —
|-
| 47:32 || — || — || — || — || — || — || — || — || — || — || — || — || — || — || — || —
|-
| 31:16 || colspan=8| red[7:0] || colspan=8| green[7:0]
|-
| 15:0 || colspan=8| blue[7:0] || colspan=8| alpha[7:0]
|}
{{#invoke:Register table|definitions
| 61:56 | command[5:0] | 0x3b
| 31:24 | red[7:0] | Environment Red value
| 23:16 | green[7:0] | Environment Green value
| 15:8 | blue[7:0] | Environment Blue value
| 7:0 | alpha[7:0] | Environment Alpha value
}}

Sets the "Environment" color register to the provided RGBA value. This color is accessible from the Color Combiner as an input.

The name "Environment" reflects only one particular usage of how the color may be used, the name does not relate to any particular meaning in the hardware.

'''Hazards'''
* This is an attribute-setting command that requires pipeline synchronization before use, otherwise currently rendering primitives may be partially rendered using both the old environment color and the new environment color, if it was used.

=== 0x3C - Set Combine Mode ===
----
{| class="wikitable" style="text-align: center; white-space:nowrap;"
! colspan="17"|Set Combine Mode <code>0x3c</code>
|-
| 63:48 || — || — || colspan=6| command = 0x3c[5:0] || colspan=4| RGB_A_0[3:0] || colspan=4| RGB_C_0[4:1]
|-
| 47:32 || RGB_C_0[0] || colspan=3| Alpha_A_0[2:0] || colspan=3| Alpha_C_0[2:0] || colspan=4| RGB_A_1[3:0] || colspan=5| RGB_C_1[4:0]
|-
| 31:16 || colspan=4| RGB_B_0[3:0] || colspan=4| RGB_B_1[3:0] || colspan=3| Alpha_A_1[2:0] || colspan=3| Alpha_C_1[2:0] || colspan=2| RGB_D_0[2:1]
|-
| 15:0 || RGB_D_0[0] || colspan=3| Alpha_B_0[2:0] || colspan=3| Alpha_D_0[2:0] || colspan=3| RGB_D_1[2:0] || colspan=3| Alpha_B_1[2:0] || colspan=3| Alpha_D_1[2:0]
|}
{{#invoke:Register table|definitions
| 61:56 | command[5:0] | 0x3c
| 55:52 | RGB_A_0[3:0] | RGB A Input (First Cycle)
| 51:47 | RGB_C_0[4:0] | RGB C Input (First Cycle)
| 46:44 | Alpha_A_0[2:0] | Alpha A Input (First Cycle)
| 43:41 | Alpha_C_0[2:0] | Alpha C Input (First Cycle)
| 40:37 | RGB_A_1[3:0] | RGB A Input (Second Cycle)
| 36:32 | RGB_C_1[4:0] | RGB C Input (Second Cycle)
| 31:28 | RGB_B_0[3:0] | RGB B Input (First Cycle)
| 27:24 | RGB_B_1[3:0] | RGB B Input (Second Cycle)
| 23:21 | Alpha_A_1[2:0] | Alpha A Input (Second Cycle)
| 20:18 | Alpha_C_1[2:0] | Alpha C Input (Second Cycle)
| 17:15 | RGB_D_0[2:0] | RGB D Input (First Cycle)
| 14:12 | Alpha_B_0[2:0] | Alpha B Input (First Cycle)
| 11:9 | Alpha_D_0[2:0] | Alpha D Input (First Cycle)
| 8:6 | RGB_D_1[2:0] | RGB D Input (Second Cycle)
| 5:3 | Alpha_B_1[2:0] | Alpha B Input (Second Cycle)
| 2:0 | Alpha_D_1[2:0] | Alpha D Input (Second Cycle)
}}

Configures the inputs to the Color Combiner pipeline stage. The Color Combiner stage computes the following equation

<math>(A - B) \cdot C + D</math>

This equation can be configured differently for
* Cycle 1 RGB
* Cycle 1 Alpha
* Cycle 2 RGB
* Cycle 2 Alpha

In 1-Cycle mode only the Cycle 2 configuration is computed, while in 2-Cycle mode both are computed and the output from Cycle 1 can be used as an input to Cycle 2. Besides some inputs behaving differently the second cycle of 2-Cycle mode and the only cycle of 1-Cycle mode behave identically, the first cycle of 2-Cycle mode is greatly simplified with no clamping occurring between combiner cycles.

'''Inputs for A (RGB)'''

{| class="wikitable"
! Value !! Name !! Description
|-
| 0 || COMBINED || Combined color from first cycle
|-
| 1 || TEX0 || Texture color sampled from the tile set in the primitive command, after texture LOD if enabled
|-
| 2 || TEX1 || Texture color sampled from the tile set in the primitive command, after texture LOD if enabled, plus one (mod 8, e.g. if TEX0 refers to tile 7, TEX1 refers to tile 0)
|-
| 3 || PRIMITIVE || Primitive color register (rgb)
|-
| 4 || SHADE || Shade color interpolated per-pixel from shade coefficients
|-
| 5 || ENVIRONMENT || Environment color register (rgb)
|-
| 6 || 1 || Fixed 1
|-
| 7 || NOISE || Per-pixel noise. This is a 9-bit value whose top 3 bits are [https://github.com/Thar0/RDP-Noise random], while the bottom 6 are fixed to 0b100000 (0x20).
|-
| 8+ || 0 || Fixed 0
|}

'''Inputs for A (Alpha)'''

{| class="wikitable"
! Value !! Name !! Description
|-
| 0 || COMBINED || Combined alpha from first cycle
|-
| 1 || TEX0 || Texture alpha sampled from the tile set in the primitive command, after texture LOD if enabled
|-
| 2 || TEX1 || Texture alpha sampled from the tile set in the primitive command, after texture LOD if enabled, plus one (mod 8, e.g. if TEX0 refers to tile 7, TEX1 refers to tile 0)
|-
| 3 || PRIMITIVE || Primitive color register (alpha)
|-
| 4 || SHADE || Shade alpha interpolated per-pixel from shade coefficients
|-
| 5 || ENVIRONMENT || Environment color register (alpha)
|-
| 6 || 1 || Fixed 1
|-
| 7 || 0 || Fixed 0
|}

'''Inputs for B (RGB)'''

{| class="wikitable"
! Value !! Name !! Description
|-
| 0 || COMBINED || Combined color from first cycle
|-
| 1 || TEX0 || Texture color sampled from the tile set in the primitive command, after texture LOD if enabled
|-
| 2 || TEX1 || Texture color sampled from the tile set in the primitive command, after texture LOD if enabled, plus one (mod 8, e.g. if TEX0 refers to tile 7, TEX1 refers to tile 0)
|-
| 3 || PRIMITIVE || Primitive color register (rgb)
|-
| 4 || SHADE || Shade color interpolated per-pixel from shade coefficients
|-
| 5 || ENVIRONMENT || Environment color register (rgb)
|-
| 6 || CENTER || Chroma key center (see '''Set Key R''' and '''Set Key GB''')
|-
| 7 || K4 || K4 value (see '''Set Convert''')
|-
| 8+ || 0 || Fixed 0
|}

'''Inputs for B (Alpha)'''

{| class="wikitable"
! Value !! Name !! Description
|-
| 0 || COMBINED || Combined alpha from first cycle
|-
| 1 || TEX0 || Texture alpha sampled from the tile set in the primitive command, after texture LOD if enabled
|-
| 2 || TEX1 || Texture alpha sampled from the tile set in the primitive command, after texture LOD if enabled, plus one (mod 8, e.g. if TEX0 refers to tile 7, TEX1 refers to tile 0)
|-
| 3 || PRIMITIVE || Primitive color register (alpha)
|-
| 4 || SHADE || Shade alpha interpolated per-pixel from shade coefficients
|-
| 5 || ENVIRONMENT || Environment color register (alpha)
|-
| 6 || 1 || Fixed 1
|-
| 7 || 0 || Fixed 0
|}

'''Inputs for C (RGB)'''

{| class="wikitable"
! Value !! Name !! Description
|-
| 0 || COMBINED || Combined color from first cycle
|-
| 1 || TEX0 || Texture color sampled from the tile set in the primitive command, after texture LOD if enabled
|-
| 2 || TEX1 || Texture color sampled from the tile set in the primitive command, after texture LOD if enabled, plus one (mod 8, e.g. if TEX0 refers to tile 7, TEX1 refers to tile 0)
|-
| 3 || PRIMITIVE || Primitive color register (rgb)
|-
| 4 || SHADE || Shade color interpolated per-pixel from shade coefficients
|-
| 5 || ENVIRONMENT || Environment color register (rgb)
|-
| 6 || SCALE || Chroma key scale (see '''Set Key R''' and '''Set Key GB''')
|-
| 7 || COMBINED_ALPHA || Combined alpha from first cycle
|-
| 8 || TEX0_ALPHA || Texture alpha sampled from the tile set in the primitive command, after texture LOD if enabled
|-
| 9 || TEX1_ALPHA || Texture alpha sampled from the tile set in the primitive command, after texture LOD if enabled, plus one
|-
| 10 || PRIMITIVE_ALPHA || Primitive color register (alpha)
|-
| 11 || SHADE_ALPHA || Shade alpha interpolated per-pixel from shade coefficients
|-
| 12 || ENVIRONMENT_ALPHA || Environment color register (alpha)
|-
| 13 || LOD_FRACTION || LOD Fraction computed as part of Texture LOD
|-
| 14 || PRIM_LOD_FRAC || Primitive LOD Fraction (see '''Set Primitive Color''')
|-
| 15 || K5 || K5 value (see '''Set Convert''')
|-
| 16+ || 0 || Fixed 0
|}

'''Inputs for C (Alpha)'''

{| class="wikitable"
! Value !! Name !! Description
|-
| 0 || LOD_FRACTION || LOD Fraction computed as part of Texture LOD
|-
| 1 || TEX0 || Texture alpha sampled from the tile set in the primitive command, after texture LOD if enabled
|-
| 2 || TEX1 || Texture alpha sampled from the tile set in the primitive command, after texture LOD if enabled, plus one (mod 8, e.g. if TEX0 refers to tile 7, TEX1 refers to tile 0)
|-
| 3 || PRIMITIVE || Primitive color register (alpha)
|-
| 4 || SHADE || Shade alpha interpolated per-pixel from shade coefficients
|-
| 5 || ENVIRONMENT || Environment color register (alpha)
|-
| 6 || PRIM_LOD_FRAC || Primitive LOD Fraction (see '''Set Primitive Color''')
|-
| 7 || 0 || Fixed 0
|}

'''Inputs for D (RGB)'''

{| class="wikitable"
! Value !! Name !! Description
|-
| 0 || COMBINED || Combined color from first cycle
|-
| 1 || TEX0 || Texture color sampled from the tile set in the primitive command, after texture LOD if enabled
|-
| 2 || TEX1 || Texture color sampled from the tile set in the primitive command, after texture LOD if enabled, plus one (mod 8, e.g. if TEX0 refers to tile 7, TEX1 refers to tile 0)
|-
| 3 || PRIMITIVE || Primitive color register (rgb)
|-
| 4 || SHADE || Shade color interpolated per-pixel from shade coefficients
|-
| 5 || ENVIRONMENT || Environment color register (rgb)
|-
| 6 || 1 || Fixed 1
|-
| 7 || 0 || Fixed 0
|}

'''Inputs for D (Alpha)'''

{| class="wikitable"
! Value !! Name !! Description
|-
| 0 || COMBINED || Combined alpha from first cycle
|-
| 1 || TEX0 || Texture alpha sampled from the tile set in the primitive command, after texture LOD if enabled
|-
| 2 || TEX1 || Texture alpha sampled from the tile set in the primitive command, after texture LOD if enabled, plus one (mod 8, e.g. if TEX0 refers to tile 7, TEX1 refers to tile 0)
|-
| 3 || PRIMITIVE || Primitive color register (alpha)
|-
| 4 || SHADE || Shade alpha interpolated per-pixel from shade coefficients
|-
| 5 || ENVIRONMENT || Environment color register (alpha)
|-
| 6 || 1 || Fixed 1
|-
| 7 || 0 || Fixed 0
|}

'''Hazards'''
* This is a pipeline configuration command that requires pipeline synchronization before use, otherwise currently rendering primitives may be partially rendered using both the old combiner configuration and the new combiner configuration.
* In 1-Cycle mode only the second cycle configuration is used, the first cycle configuration is ignored.
* COMBINED in the first cycle (or in 1-Cycle mode) is ill-defined. It will (generally) read the previous pixel combiner output. ([[Reality Display Processor/Hazards#RH#003|RH#003]])
* If using the SHADE input the primitive must have provided shade coefficients. The SHADE input is therefore always invalid for rectangle commands as there is no option for providing shade coefficients for those. ([[Reality Display Processor/Hazards#RH#004|RH#004]])
* If using the TEX0/1 inputs the primitive must have provided texture coordinates and a tile number. Fill Rectangles cannot provide either of these so these options are always invalid for those.
* If using the LOD_FRACTION input, Texture LOD must have been enabled in othermodes.
* In 1-Cycle mode, LOD_FRACTION is not valid. (TOVERIFY in what way is it not valid? Does the 1-Cycle pipeline bypass LOD altogether, so does not update this input?)
* In 1-Cycle mode, TEX1 reads next pixel TEX0 (with some ambiguity at scanline edges) ([[Reality Display Processor/Hazards#RH#001|RH#001]])
* In 2-Cycle mode there is a pipeline bug involving TEX0 and TEX1. In the second cycle of 2-Cycle mode, TEX0 refers to TEX1 and TEX1 refers to next pixel TEX0 (with some ambiguity at scanline edges) ([[Reality Display Processor/Hazards#RH#002|RH#002]])
* The color combiner is quick to overflow. Values between 256 and 383 saturate to 255 while 384 to 511 overflow to 0. Values greater than or equal to 512 overflow the 9-bit color completely.
* Sign-extension properties differ between the A,B,D and C inputs. C is more prone to overflow, it is advisable to keep the COMBINED input out of the C input as much as possible.
* The 1 input is valued at 256, not 255. This may contribute to overflow issues.

=== 0x3D - Set Texture Image ===
----
{| class="wikitable" style="text-align: center; white-space:nowrap;"
! colspan="17"|Set Texture Image <code>0x3d</code>
|-
| 63:48 || — || — || colspan=6| command = 0x3d[5:0] || colspan=3| format[2:0] || colspan=2| size[1:0] || — || — || —
|-
| 47:32 || — || — || — || — || — || — || colspan=10| width[9:0]
|-
| 31:16 || — || — || — || — || — || — || — || — || colspan=8| dramAddress[23:16]
|-
| 15:0 || colspan=16| dramAddress[15:0]
|}
{{#invoke:Register table|definitions
| 61:56 | command[5:0] | 0x3d
| 55:53 | format[2:0] | Texture image format
| 52:51 | size[1:0] | Texture image pixel size
| 41:32 | width[9:0] | Texture image width in pixels (-1) (possible range of 1 to 4096 pixels)
| 23:0 | dramAddress[23:0] | RDRAM physical address of the buffer containing texture data
}}

Sets the texture image, the location in RDRAM where the texture loading pipeline should source image data, and related properties.

The texture image format parameter seems to have no function, it has no effect on any operation unlike the tile format.
{| class="wikitable"
! Format Name !! Format Value
|-
| RGBA || 0
|-
| YUV || 1
|-
| Color-Indexed (CI) || 2
|-
| Intensity-Alpha (IA) || 3
|-
| Intensity (I) || 4+
|}

The size parameter is used to increment the RDRAM address during texture loading.
{| class="wikitable"
! Bits per pixel !! Size Value
|-
| 4 || 0
|-
| 8 || 1
|-
| 16 || 2
|-
| 32 || 3
|}

The width parameter is used to calculate the start address of each texture image row during loading.

This is an attribute-setting command but is not used in the rendering pipeline so does not require a pipeline synchronization before changing it. (TOVERIFY is a sync required if changing it following a load command?)

'''Hazards'''
* Memory alignment should be 8-byte to guarantee operation. If the address falls into the range [1,7] mod 64, the RDP may hang when loading from it.

=== 0x3E - Set Depth Image ===
----
{| class="wikitable" style="text-align: center; white-space:nowrap;"
! colspan="17"|Set Depth Image <code>0x3e</code>
|-
| 63:48 || — || — || colspan=6| command = 0x3e[5:0] || — || — || — || — || — || — || — || —
|-
| 47:32 || — || — || — || — || — || — || — || — || — || — || — || — || — || — || — || —
|-
| 31:16 || — || — || — || — || — || — ||  — ||  — || colspan=8| dramAddress[23:16]
|-
| 15:0 || colspan=16| dramAddress[15:0]
|}
{{#invoke:Register table|definitions
| 61:56 | command[5:0] | 0x3e
| 23:0 | dramAddress[23:0] | RDRAM physical address of the buffer to store depth information
}}

Sets the depth image, the region in RDRAM where depth information will be stored. The depth image width is the same as the image width for the current color image. The depth buffer format is a fixed 18-bit-per-pixel format irrespective of the color image format.

'''Hazards'''
* This attribute must be set before rendering any primitives that read or write depth, else it will read/write depth data at an unspecified location.
* Memory alignment must be 64-byte for all rendering operations to behave as expected.

=== 0x3F - Set Color Image ===
----
{| class="wikitable" style="text-align: center; white-space:nowrap;"
! colspan="17"|Set Color Image <code>0x3f</code>
|-
| 63:48 || — || — || colspan=6| command = 0x3f[5:0] || colspan=3| format[2:0] || colspan=2| size[1:0] || — || — || —
|-
| 47:32 || — || — || — || — || — || — || colspan=10| width[9:0]
|-
| 31:16 || — || — || — || — || — || — ||  — ||  — || colspan=8| dramAddress[23:16]
|-
| 15:0 || colspan=16| dramAddress[15:0]
|}
{{#invoke:Register table|definitions
| 61:56 | command[5:0] | 0x3f
| 55:53 | format[2:0] | Pixel format (same meaning as in texture format)
| 52:51 | size[1:0] | Pixel size  (same meaning as in texture size)
| 41:32 | width[9:0] | Image width in pixels (-1) (possible range of 1 to 4096 pixels)
| 23:0 | dramAddress[23:0] | RDRAM physical address of the buffer where pixels will be written
}}

Sets the color image address and properties, the region in RDRAM where primitives will be rendered to as pixels.

The image is arrayed in row-order, that is rows are adjacent in memory. It is generally more efficient to draw wide triangles rather than horizontally thin triangles that overlap many rows; for single rows span buffers are employed to alleviate stalls due to waiting on memory read/write requests while there is no such buffering across multiple rows.

Valid format/size combinations are RGBA32, RGBA16, I8. 4-bit modes only write 0s as bytes, all 8-bit modes behave identically, 16-bit and 32-bit RGBA modes differ from other modes.

'''Hazards'''
* This attribute must be set before rendering any primitives, else it will render to an unspecified location.
* This is an attribute-setting command that requires pipeline synchronization before use, otherwise currently rendering primitives may be split partially between the old color image and new color image. (TOVERIFY there are conflicting accounts of whether Set Color Image requires a sync, the current consensus is that sync is required to avoid all edge cases)
* Memory alignment must be 64-byte for all rendering operations to behave as expected.
* Rendering any primitive in FILL mode to a 4-bit color image will crash the RDP.
* Copying a 4-bit or 8-bit texture with COPY mode is only possible if the destination color image is 8-bit.
* Copying a 16-bit texture with COPY mode is only possible if the destination color image is 16-bit. (Note that CI textures are treated as 16-bit in COPY mode as the TLUT is 16-bit)
* COPY mode is unavailable when a 32-bit color image is configured.
