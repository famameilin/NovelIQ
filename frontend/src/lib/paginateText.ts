/** Split a long diagnosis into readable screen-sized passages without dropping any text. */
export function paginateText(text: string, maxLength = 220): string[] {
  const normalized = text.trim();
  if (!normalized) return [];

  const sentences = normalized.match(/[^。！？；;!?]+[。！？；;!?]?/g) ?? [normalized];
  const pages: string[] = [];
  let current = "";

  for (const sentence of sentences) {
    let rest = sentence;
    while (rest.length > 0) {
      const available = maxLength - current.length;
      if (available === 0) {
        pages.push(current);
        current = "";
        continue;
      }
      if (rest.length <= available) {
        current += rest;
        break;
      }
      if (current) {
        pages.push(current);
        current = "";
        continue;
      }
      pages.push(rest.slice(0, maxLength));
      rest = rest.slice(maxLength);
    }
  }

  if (current) pages.push(current);
  return pages;
}
