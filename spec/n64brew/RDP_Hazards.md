<!--
  Source: https://n64brew.dev/wiki/Reality_Display_Processor/Hazards
  Authors: N64brew Wiki contributors
  License: CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/)
-->

RDP programming is full of hazards. It is by far the most complex part of the console and the silicon is extremely intolerant to wrong configurations. Most users trying to manually programming the chip without the help of a higher level library (such as libdragon's rdpq) often face issues such as rendering glitches or even RDP crashes.

This page tries to list all known RDP hazards. Each hazard is assigned a unique code, to simplify identification and discussion. A metadata table for each hazard is also provided:
{| class="wikitable"
|+
!Key
!Description
|-
|Type
|Categorize hazards depending on their effect. Possible values are:

* '''Glitch:''' the hazard will cause a minor graphic issue, that might even not be noticable
* '''Corruption:''' the hazard will cause a large and visible graphical that is hard to miss in most cases
* '''Crash:''' the RDP will crash. When crashed, it stops processing further commands. The only way to recover is to hard reset the console.
|-
|Validator
|Whether the Libdragon rdpq validator will detect and report this hazard, or not
|-
|Libdragon
|Whether Libdragon rdpq library shields programmers from hitting this hazard, or not
|-
|Ares
|Whether Ares will emulate the effects on this hazard matching the hardware behavior, or not
|}

== RH#001 ==
{| class="wikitable" style="text-align: center; white-space:nowrap;"
! Type !! Validator !! Libdragon !! Ares
|-
|| Corruption || {{tick|color=green}} || {{tick|color=green}} || {{cross|color=red}} 
|}

; Description : Invalid access to the TEX1 / TEX1_ALPHA combiner input in 1-Cycle Mode
; Effect : TEX1 or TEX1_ALPHA will contain the value of the next pixel in the same scanline, and garbage date on the last visible pixel on each scanline.
; Workaround: If you need to sample two textures in the combiner, you must use the 2-Cycle Mode instead.
; Programming notes: '''Libdragon:''' Trying to use TEX1 or TEX1_ALPHA in a 1-step combiner causes a compile-time error, so it should not be possible to trigger this bug.

== RH#002 ==
{| class="wikitable" style="text-align: center; white-space:nowrap;"
! Type !! Validator !! Libdragon !! Ares
|-
|| Corruption || {{tick|color=green}} || {{tick|color=green}} || {{cross|color=red}} 
|}

; Description: Invalid access to the TEX1 combiner input in the second cycle of 2-Cycle Mode
; Effect: In the second cycle, the values of the TEX0 and TEX1 combiner inputs behave weirdly because of pipelining bugs:
:* TEX1 will contain the value of the next pixel of the ''first texture'' in the same scanline, and garbage date on the last visible pixel on each scanline.
:* TEX0 instead will refer to the current pixel of the ''second texture'' (that is, the same value you would access via TEX1 in the first cycle).
{| class="wikitable"
|+Combiner inputs in 2-Cycle Mode
!
!TEX0
!TEX1
|-
|First cycle
|Current pixel of the first texture
|Current pixel of the second texture
|-
|Second cycle
|Current pixel of the second texture
|Next pixel of the first texture
(or garbage on the last pixel of the scanline)
|}
:
; Workaround: Restructure your combiner in a way not to access the second texture in the second cycle if possible, since there is no way to do so.
; Programming notes: '''Libdragon:''' In rdpq, the slots have been renamed to avoid the confusing. In the second cycle, you must use TEX1 to refer to the current pixel of the first texture (just like you do in the first cycle), and TEX0_BUG if you absolutely want to sample the first texture's next pixel. This tries to hide a bit the hazard, by at least uniformly mapping TEX0* to the first texture and TEX1 to the second texture.
; Affected games: '''Monster Truck Madness''' The text in the menu will appear corrupted if an emulator doesn't correctly reproduce the behavior of this hazard.

== RH#003 ==
{| class="wikitable" style="text-align: center; white-space:nowrap;"
! Type !! Validator !! Libdragon !! Ares
|-
|| Corruption || {{tick|color=green}} || {{tick|color=green}} || {{cross|color=red}} 
|}

; Description : Invalid access to the COMBINED/COMBINED_ALPHA combiner input in first combiner cycle
; Effect : Accessing COMBINED or COMBINED_ALPHA in the first combiner cycle (that is, the only cycle in 1-Cycle Mode, or the first cycle in 2-Cycle Mode) will provide the either output of the combiner of the previous pixel, or garbage data on the first pixel of the scanline.
; Workaround: It is meaningless to use COMBINED/COMBINED_ALPHA in the first cycle, as their goal is to access the output of the first cycle. Program your combiner correctly.
; Programming notes: '''Libdragon:''' Trying to use COMBINED or COMBINED_ALPHA in a the first step of a combiner causes a compile-time error, so it should not be possible to trigger this bug.

== RH#004 ==
{| class="wikitable" style="text-align: center; white-space:nowrap;"
! Type !! Validator !! Libdragon !! Ares
|-
|| Corruption || {{tick|color=green}} || {{tick|color=green}} || {{cross|color=red}} 
|}

; Description : Invalid access to the SHADE/SHADE_ALPHA combiner input in non-shaded primitive.
; Effect : On non-shaded primitives (triangles without color components, or rectangles), the SHADE and SHADE_ALPHA combiner inputs will contain garbage
; Workaround: Make sure that your triangles contain a color component (RGBA) on each vertex, as the per-pixel interpolation of that component is what the SHADE input is meant to represent. If you need to draw a rectangle, you need to split it into two triangles, as RDP rectangles does not allow a color component to be specified.
; Programming notes: '''Libdragon:''' When using rdpq_triangle, make sure to specify a format that includes shades (eg: TRIFMT_SHADE). To draw a rectangle with per-vertex color, split it into two triangles with two calls to rdpq_triangle.
