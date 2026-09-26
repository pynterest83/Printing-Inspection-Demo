# Dataset and artwork attribution

The five-lane packaging background in `taktpixel_roll/` uses:

- **Lulu La Barquette Framboise**, product code `3017760038676`
- Source image: https://world.openfoodfacts.org/product/3017760038676
- Image database: Open Food Facts, https://openfoodfacts.org
- License: Creative Commons Attribution-ShareAlike 3.0 (CC BY-SA 3.0),
  https://creativecommons.org/licenses/by-sa/3.0/

The source photograph is cropped, resized, repeated into five lanes, and given
deterministic camera-style degradation. Product names and trademarks remain the
property of their respective owners; their presence does not imply endorsement.

The prepared demo roll in `taktpixel_roll/` is derived from:

- **Taktpixel2025PD-CD: Taktpixel 2025 Printing Defect Change Detection Dataset**
- Author: Teppei Tamaki / Taktpixel Co., Ltd.
- DOI: https://doi.org/10.5281/zenodo.15318946
- Source: https://github.com/taktpixel/Taktpixel2025PD-CD
- License: Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)

The prepared roll transfers defect residuals from source `A`/`B` image pairs
onto the packaging master and applies deterministic camera-style noise. The
upstream `OUT` masks are used only while preparing and evaluating the roll;
they are not read by the runtime detector. See the applicable ShareAlike terms
for both sources when redistributing the derived image assets.
