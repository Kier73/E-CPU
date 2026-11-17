#include <stdint.h>
/* Independent WebAssembly realizer for SAB-008 affine modular navigation.
 * Values are bounded by the surrounding strict contract (m <= 65521).
 * Intermediate products fit unsigned 64-bit; logical time is not replayed. */
__attribute__((export_name("affine_at")))
uint32_t affine_at(uint32_t a, uint32_t c, uint32_t m, uint32_t seed, uint64_t t) {
  uint64_t p = 1, q = 0, mul = a, add = c;
  while (t) {
    if (t & 1) { p = (p * mul) % m; q = (q * mul + add) % m; }
    add = (add * (mul + 1)) % m;
    mul = (mul * mul) % m;
    t >>= 1;
  }
  return (p * seed + q) % m;
}
