import "server-only";

/** ISR / data cache lifetime. Daily UPDATE_TODAY uploads appear within this window. */
export const CARD_REVALIDATE = 300;
/** Tag used by the optional /api/revalidate route to drop the cache early. */
export const CARD_TAG = "card";
