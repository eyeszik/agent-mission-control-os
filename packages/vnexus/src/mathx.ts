/**
 * Correctly rounded `log` and `statistics.NormalDist().inv_cdf` (Wichura AS241,
 * the same operation order as CPython). V8's `Math.log` is not bit-identical to
 * the C library's (about 7% of random inputs differ by one ulp), and the
 * tail branch of `inv_cdf` feeds `log` straight into every sample size, so the
 * logarithm is computed in 128-bit fixed point and rounded once.
 */
import { StatisticsError } from './errors';

const PRECISION = 128n;
const ONE = 1n << PRECISION;

function fixedDivide(a: bigint, b: bigint): bigint {
  return (a << PRECISION) / b;
}

/** atanh(z) in fixed point by its power series (ln 2 = 2 * atanh(1/3)). */
function atanhFixed(z: bigint): bigint {
  const z2 = (z * z) >> PRECISION;
  let term = z;
  let sum = 0n;
  for (let k = 1n; term !== 0n; k += 2n) {
    sum += term / k;
    term = (term * z2) >> PRECISION;
  }
  return sum;
}

const LN2 = 2n * atanhFixed(fixedDivide(1n, 3n));

function decompose(x: number): { mantissa: bigint; exponent: number } {
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, x);
  const hi = view.getUint32(0);
  const biased = (hi >>> 20) & 0x7ff;
  const fraction = (BigInt(hi & 0xfffff) << 32n) | BigInt(view.getUint32(4));
  return biased === 0 ? { mantissa: fraction, exponent: -1074 } : { mantissa: fraction | (1n << 52n), exponent: biased - 1075 };
}

/** `math.log(x)` for finite x > 0, correctly rounded. */
export function log(x: number): number {
  if (!(x > 0) || !Number.isFinite(x)) throw new RangeError('math domain error');
  const { mantissa, exponent } = decompose(x);
  const bits = mantissa.toString(2).length;
  const e = exponent + bits - 1; // x = m * 2^e with m in [1, 2)
  const m = mantissa << (PRECISION - BigInt(bits - 1));
  const z = fixedDivide(m - ONE, m + ONE);
  const ln = 2n * atanhFixed(z) + BigInt(e) * LN2;
  return Number(ln) * 2 ** -128;
}

/** CPython's C `_normal_dist_inv_cdf(p, mu, sigma)` (AS241), operation for operation. */
function inverseCdf(p: number): number {
  const q = p - 0.5;
  if (Math.abs(q) <= 0.425) {
    const r = 0.180625 - q * q;
    const num = (((((((2.5090809287301226727e+3 * r + 3.3430575583588128105e+4) * r + 6.7265770927008700853e+4) * r
      + 4.5921953931549871457e+4) * r + 1.3731693765509461125e+4) * r + 1.9715909503065514427e+3) * r
      + 1.3314166789178437745e+2) * r + 3.3871328727963666080e+0) * q;
    const den = (((((((5.2264952788528545610e+3 * r + 2.8729085735721942674e+4) * r + 3.9307895800092710610e+4) * r
      + 2.1213794301586595867e+4) * r + 5.3941960214247511077e+3) * r + 6.8718700749205790830e+2) * r
      + 4.2313330701600911252e+1) * r + 1.0);
    return num / den;
  }
  let r = q <= 0.0 ? p : 1.0 - p;
  r = Math.sqrt(-log(r));
  let num: number;
  let den: number;
  if (r <= 5.0) {
    r -= 1.6;
    num = (((((((7.7454501427834140764e-4 * r + 2.2723844989269184583e-2) * r + 2.4178072517745061177e-1) * r
      + 1.2704582524523683826e+0) * r + 3.6478483247632045960e+0) * r + 5.7694972214606914055e+0) * r
      + 4.6303378461565452959e+0) * r + 1.4234371107496835773e+0);
    den = (((((((1.0507500716444168432e-9 * r + 5.4759380849953449460e-4) * r + 1.5198666563616457197e-2) * r
      + 1.4810397642748007459e-1) * r + 6.8976733498510000455e-1) * r + 1.6763848301838038494e+0) * r
      + 2.0531916266377588219e+0) * r + 1.0);
  } else {
    r -= 5.0;
    num = (((((((2.0103343992922881327e-7 * r + 2.7115555687434875782e-5) * r + 1.2426609473880784386e-3) * r
      + 2.6532189526576123093e-2) * r + 2.9656057182850489123e-1) * r + 1.7848265399172913358e+0) * r
      + 5.4637849111641143699e+0) * r + 6.6579046435011037772e+0);
    den = (((((((2.0442631033899397856e-15 * r + 1.4215117583164458887e-7) * r + 1.8463183175100546818e-5) * r
      + 7.8686913114561325910e-4) * r + 1.4875361290850614852e-2) * r + 1.3692988092273580531e-1) * r
      + 5.9983220655588793769e-1) * r + 1.0);
  }
  const x = num / den;
  return q < 0.0 ? -x : x;
}

/** `NormalDist().inv_cdf(p)`. */
export function normalInvCdf(p: number): number {
  if (!(p > 0.0 && p < 1.0)) throw new StatisticsError('p must be in the range 0.0 < p < 1.0');
  return inverseCdf(p);
}
