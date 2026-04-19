import { describe, expect, test } from "vitest";
import { indianNumber, rupee } from "@/lib/format";

describe("Indian number formatting", () => {
  test("basic lakh grouping", () => {
    expect(rupee(240000)).toBe("₹2,40,000");
    expect(rupee(192000)).toBe("₹1,92,000");
  });
  test("small numbers unchanged", () => {
    expect(rupee(0)).toBe("₹0");
    expect(rupee(999)).toBe("₹999");
    expect(rupee(1000)).toBe("₹1,000");
  });
  test("crore scale", () => {
    expect(indianNumber(10000000)).toBe("1,00,00,000");
  });
  test("negatives", () => {
    expect(rupee(-8000)).toBe("-₹8,000");
  });
});
