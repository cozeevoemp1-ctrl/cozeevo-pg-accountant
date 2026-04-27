export function indianNumber(n: number): string {
  const abs = Math.abs(n);
  const s = abs.toString();
  const last3 = s.slice(-3);
  const rest = s.slice(0, -3);
  const withCommas = rest.length
    ? rest.replace(/\B(?=(\d{2})+(?!\d))/g, ",") + "," + last3
    : last3;
  return n < 0 ? `-${withCommas}` : withCommas;
}

export function rupee(n: number): string {
  if (n < 0) {
    return `-₹${indianNumber(-n)}`;
  }
  return `₹${indianNumber(n)}`;
}

export function rupeeL(n: number): string {
  return rupee(n);
}
