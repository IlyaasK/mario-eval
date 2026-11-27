<!--
  Source: https://n64brew.dev/wiki/Reality_Display_Processor/Pipeline
  Authors: N64brew Wiki contributors
  License: CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/)
-->


The RDP has four operating modes controlled by the '''cycle_type''' field in the [[Reality_Display_Processor/Commands#0x2F_-_Set_Other_Modes|Set Other Modes]] command. These modes determine how each pixel in the RDP pipeline is processed.

* '''1-Cycle Mode''': 1 cycle (@ 62.5 MHz) per pixel (pipelined) with all pipeline stages active
* '''2-Cycle Mode''': 2 cycles (@ 62.5 MHz) Per pixel (pipelined) with all pipeline stages active, some running twice per pixel
* '''Fill Mode''': Accelerated rendering of solid-color rectangles
* '''Copy Mode''': Accelerated blitting of sprites with no additional processing

The RDP also has a separate loading pipeline that is selected when load commands ([[Reality_Display_Processor/Commands#0x33_-_Load_Block|Load Block]], [[Reality_Display_Processor/Commands#0x34_-_Load_Tile|Load Tile]], or [[Reality_Display_Processor/Commands#0x30_-_Load_TLUT|Load TLUT]]) are executed. This shares some resources with the rendering pipelines to save hardware cost.


== 1-Cycle Pipeline ==

The 1-Cycle pipeline renders any combination of shaded, textured, z-buffered, anti-aliased primitives, each with one stage of texturing, color combiner and blending. The pipeline can be broken down as follows, however note that some of these stages may be executed in parallel and some may be spread out over multiple clock cycles so consider this a logical view of the pipeline only.

(TODO: each of these stages deserves much more detail on their operation, either on this page or in subpages)

* '''Rasterize'''<br>Determines the set of pixels that the primitive should cover. Interpolates the necessary attributes of the primitive for each pixel such as shade color, depth value and texture coordinates. Computes a coverage value for each pixel. Only once the last pixel in the primitive has been enqueued into the first stage of the rest of the pipeline are any new RDP commands executed.
* '''Texture Perspective Correction'''<br>Only if '''persp_tex_en''' enabled. Divides the (s,t) attributes of each pixel by the pixel's ''w'' attribute.
* '''Texture Coordinate Shift, Clamp, Mirror, Mask'''<br>This stage maps the input texture coordinates for the primitive into local texture coordinates for the texture tile this primitive is to be rendered with. Conversion to relative texture coordinates by subtracting the tile's upper-left (s,t) coordinates happens between shift and clamp.
* '''Texture Sampling'''<br>Four texels are sampled from TMEM using the results of the prior steps. All texels irrespective of storage format are converted to RGBA32 when sampled.
* '''Texture Filtering'''<br>The four texel samples are combined into a single result by the selected filter mode.
* '''RGBA and Depth Correction'''<br>The RGBA shade color and depth value are subpixel-corrected using the computed coverage value.
* '''Color Combiner'''<br>The Color Combiner is evaluated on its inputs to produce the output color.
* '''Chroma Key'''<br>(TODO)
* '''Alpha Fixup'''<br>Using '''cvg_x_alpha''' and '''alpha_cvg_sel''', adjusts the alpha value output from the color combiner and also adjusts the coverage value seen by later stages.
* '''Dither Shade Alpha'''<br>Apply alpha dither to interpolated shade alpha for use as a blender input. If '''alpha_cvg_select''' is disabled, also applies to alpha used for alpha compare.
* '''Image Read'''<br>If '''image_read_en''' is set in othermodes, read memory color and coverage from color image. If disabled, memory coverage is set to full (7) and memory color is undefined.
* '''Depth Compare and Blend Enable Generation'''<br>If '''z_compare_en''' is set in othermodes. Depth compare algorithm determined by '''z_mode''' in othermodes. Depth source determined by '''z_source_sel''' in othermodes. Blending is enabled if either '''force_bl''' is set or if '''antialias_en''' is set and the pixel is determined to be an edge pixel. If a pixel fails the depth test it is discarded and is not written to the color image.
* '''Alpha Compare'''<br>Alpha compare enabled if '''alpha_compare_en''' is set in othermodes. If a pixel fails the alpha compare test, discard it.
* '''Coverage Pixel Rejection'''<br>If '''antialias_en''' is set and coverage is 0, discard the pixel. If '''antialias_en''' unset and LSB of coverage is 0, discard the pixel.
* '''Blender'''<br>If '''clr_on_cvg''' is set and coverage has overflowed, take the memory color as-is and do not blend. If the blend enable signal generated earlier in the pipeline is true, perform blending by evaluating the blender on its inputs. If blending was not enabled, take the value of the first input to the blender as-is. When blending, only divide if '''force_bl''' is not set. The alpha input to the blender is reduced to 5 bits by taking the most significant 5 bits.
* '''RGB Dither'''<br>Perform RGB dithering, reduce color depth from 8-bit per channel to 5-bit per channel if targeting a 16-bit color image.
* '''Color Image Write'''<br>Pixels that are not rejected by earlier stages are written to the on-chip span buffers to await flushing to RDRAM.
* '''Depth Image Write'''<br>If '''z_update_en''' is set, write the new depth value for this pixel to the depth span to await flushing to the Z-Buffer in RDRAM.

== 2-Cycle Pipeline ==

The 2-Cycle pipeline renders any combination of shaded, textured, z-buffered, anti-aliased primitives, each with two stages of texturing, color combiner and blending. The pipeline is much like the 1-Cycle pipeline but with two consecutive texturing stages, two consecutive color combine stages, and two consecutive blending stages. Unlike the 1-Cycle pipeline, beware the many pipeline hazards the 2-Cycle pipeline presents, many of which are so far documented on the [[Reality_Display_Processor/Commands|RDP Commands page]].

== Fill Pipeline ==

The Fill pipeline is the simplest of the pipelines, it retains only enough functionality to fill screen regions with a solid color sourced from the fill color register.

* '''Rasterize'''<br>Determines the set of pixels that the primitive should cover. Unlike 1 and 2-cycle modes most attributes are not interpolated and no coverage is computed. Texture coordinates are not generated.
* '''Color Image Write'''<br>Writes pixels out to the color image using the current fill color value. Pixels are written out 64-bits (8 8-bit pixels, 4 16-bit pixels, 2 32-bit pixels) at a time. Writes are committed straight to RDRAM without passing through the span buffers.

== Copy Pipeline ==

The Copy pipeline is relatively simple, many of the core pipeline features as skipped to enable fast copying of textures from TMEM directly to the color image with few changes.

* '''Rasterize'''<br>Determines the set of pixels that the primitive should cover. Texture coordinates are interpolated for each pixel.
* '''Texture Perspective Correction'''<br>Performs perspective correction of texture coordinates if '''persp_tex_en''' is set in othermodes. This is expected to be disabled in general.
* '''Texture Coordinate Shift, Mirror and Mask'''<br>Performs shifting, mirroring and masking of texture coordinates using the shift, mirror and mask values specified by the selected texture tile. Shifting is applied before subtracting the tile upper-left (s,t) values, mirroring and then masking is applied after the subtraction to tile-relative texture coordinates. Clamping is not performed in Copy mode.
* '''Texture Sampling and TLUT Decoding'''<br>Samples texels from TMEM using the tile-relative texture coordinates. If '''tlut_en''' is set in othermodes the final texel will be sourced from a palette and the tile format is ignored, for tiles that indicate a 4-bit texel size the TMEM address for the palette is indicated in the tile's palette field, the tile size is otherwise ignored. Texels are sampled 64-bits at a time irrespective of tile format/size configuration.
* '''Alpha Compare'''<br>Performs alpha compare on the sampled texels if '''alpha_compare_en''' is set in othermodes, only those texels passing the alpha compare test are written out to the color image as pixels. The precise operation of alpha compare varies depending on the selected color image format (notably, NOT the render tile format):
** For 16-bit color images the alpha compare test simply checks if the alpha bit (LSB) is set and if so the test passes.
** For 8-bit color images the alpha compare tests against either a random threshold or the blend color register alpha value depending on the value of '''dither_alpha_en''' in othermodes. If the 8-bit texel value is greater than or equal to the selected threshold the test passes.
** For 4-bit color images alpha compare always fails if enabled.
* '''Color Image Write'''<br>Writes all texels that passed the alpha compare test out to the color image as pixels.

== Loading Pipeline ==

The loading pipeline is only indirectly configurable (through tile settings, the [[Reality_Display_Processor/Commands#0x3D_-_Set_Texture_Image|Set Texture Image]] command, and through load commands that kick off this pipeline) and facilitates the loading of texture data from RDRAM into TMEM. The loading pipeline appears to share some resources with the rendering pipelines as they cannot be executed in parallel. It can be unsafe to run a loading command followed immediately by a primitive rendering command right away and vice-versa, the two must be separated by synchronization to let the current operation finish before the next begins.

== Synchronization ==

The RDP does not automatically interlock most global rendering attributes. Instead, it is up to the user to insert [[Reality_Display_Processor/Commands#0x27_-_Sync_Pipe|Pipe Sync]], [[Reality_Display_Processor/Commands#0x28_-_Sync_Tile|Tile Sync]], or [[Reality_Display_Processor/Commands#0x26_-_Sync_Load|Load Sync]] commands as-needed. Syncs should be inserted after primitive drawing and before attribute changes, as well as when switching between any of the rendering pipelines and the loading pipeline. Four attributes do not require sync:
* Prim Color
* Prim Depth
* Scissor
* Tile Size

All sync commands work the same way, after the current primitive/texture pixels have been determined and enqueued onto the rendering/loading pipeline, a sync will insert additional wait cycles before processing the next command waiting in the FIFO. '''Pipe Sync''' waits the longest (50 cycles), followed by '''Tile Sync''' (33 cycles) and then '''Load Sync''' (25 cycles). If syncs are not properly inserted, the RDP will adopt the new settings too early and pixels at the end of the last primitive will be produced using a mix of the old and new settings. Depending on which settings are changed, this may lead to crashes.

Different attributes are sampled at different stages in the RDP pipeline, depending on which attribute is corrupted the number of pixels affected will vary. Unsynced changes to attributes sampled towards the end of a pixel's lifetime in the pipeline will corrupt more pixels. In 1-Cycle Mode, the number of pixels corrupted is almost equal to the number of cycles corrupted, except there is 1 dead cycle at the end of every line in a primitive where the pipeline is cycled but no pixel is output. This dead cycle counts as a pixel for the purpose of counting corruptions.

{| class="wikitable"
|+ Effect of unsynced attribute changes
|-
! Global Setting Changed !! Cycles Corrupted (1-Cycle Mode) !! Cycles Corrupted (2-Cycle Mode) !! Extra Details
|-
| Depth image address      || '''TBC''' || '''TBC''' || 
|-
| Color image settings     || 0         || 0         || Applies to both the color image base address and the image format/size
|-
| image_read_en            || 0         || 0         || 
|-
| z_compare_en             || 0         || 0         || 
|-
| z_update_en              || 0         || 0         || 
|-
| convert_one              || N/A       || '''TBC''' || 
|-
| persp_tex_en             || 7         || 4         || 
|-
| Tile Settings            || 13        || 10        || Applies to any tile setting besides tile size
|-
| tex_lod_en               || 13        || 12        || 
|-
| detail_tex_en            || '''TBC''' || '''TBC''' || 
|-
| sharpen_tex_en           || '''TBC''' || '''TBC''' || 
|-
| sample_type              || 17        || 14        || 
|-
| tlut_en                  || 18        || 16        || 
|-
| tlut_type                || 20        || 18        || 
|-
| mid_texel                || 21        || 18        || 
|-
| bi_lerp_0                || 21        || '''TBC''' || 
|-
| bi_lerp_1                || 21        || '''TBC''' || 
|-
| Combiner Settings/Inputs || 24        || 22        || Applies to changing the combiner configuration, or changing any of the active inputs to the combiner (such as env color) besides prim color
|-
| Set Convert              || 24        || 22        || 
|-
| Chroma Key Parameters    || 24        || '''TBC''' || 
|-
| alpha_cvg_select         || 25        || 24        || 
|-
| cvg_x_alpha              || 25        || 24        || 
|-
| key_en                   || 25        || 24        || 
|-
| z_source_sel             || 25        || 24        || 
|-
| alpha_dither_sel         || 25        || 24        || 
|-
| Blender Settings/Inputs  || 26        || 24        || Applies to changing the blender configuration, or changing any of the active inputs to the blender (such as fog color)
|-
| dither_alpha_en          || 26        || 26        || 
|-
| z_mode                   || 27        || 26        || 
|-
| force_blend              || 27        || 26        || 
|-
| antialias_en             || 27        || 26        || 
|-
| cvg_dest                 || 28        || 28        || 
|-
| color_on_cvg             || 28        || 28        || 
|-
| rgb_dither_sel           || 29        || 28        || 
|-
| alpha_compare_en         || 29        || 28        || 
|}

The following snippet shows how attributes that require syncs are updated internally in just 1 cycle:

  // red fill rectangle
  SET ENV COLOR (255, 0, 0, 255)
  FILL RECTANGLE (...)
  // corrupt two pixels with green towards the end, without the NOP this would corrupt just one pixel as NOPs and attribute setters execute in just 1 pipeline cycle
  SET ENV COLOR (0, 255, 0, 255)
  NOP
  // corrupt remaining pixels with blue
  SET ENV COLOR (0, 0, 255, 255)
