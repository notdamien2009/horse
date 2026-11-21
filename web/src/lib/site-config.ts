/** FurlongIQ site settings. Change the membership price here and it updates everywhere on the site. */
export const SITE = {
  name: "FurlongIQ",
  /** Monthly membership price in pounds (target range £25–28). */
  priceMonthlyGBP: 25,
  /** Commission used in profit figures and the calculator default (percent). */
  commissionPct: 5,
} as const;