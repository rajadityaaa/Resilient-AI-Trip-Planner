/**
 * ics.js - RFC 5545 Compliant iCalendar Generator
 * Generates downloadable .ics files with properly folded lines and escaped characters.
 */

function escapeIcsText(text) {
  if (!text) return "";
  return String(text)
    .replace(/\\/g, "\\\\")
    .replace(/;/g, "\\;")
    .replace(/,/g, "\\,")
    .replace(/\r\n|\n|\r/g, "\\n");
}

function foldLine(line) {
  if (line.length <= 75) return line;
  const parts = [];
  let remaining = line;
  parts.push(remaining.slice(0, 75));
  remaining = remaining.slice(75);
  while (remaining.length > 0) {
    parts.push(" " + remaining.slice(0, 74));
    remaining = remaining.slice(74);
  }
  return parts.join("\r\n");
}

export function generateTripIcs(trip) {
  const itinerary = trip.daily_itinerary || [];
  const destination = trip.destination || "Trip Destination";
  const lines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//Aetheria Travel//AI Trip Planner//EN",
    "CALSCALE:GREGORIAN",
    "METHOD:PUBLISH",
  ];

  const nowIso = new Date().toISOString().replace(/[-:]/g, "").split(".")[0] + "Z";

  itinerary.forEach((dayItem, idx) => {
    const rawDate = dayItem.date; // YYYY-MM-DD
    if (!rawDate) return;
    const dateClean = rawDate.replace(/-/g, "");

    const blocks = [
      { name: "Morning", summary: `${destination} - Day ${dayItem.day || idx + 1} Morning`, text: dayItem.morning, start: "090000", end: "120000" },
      { name: "Afternoon", summary: `${destination} - Day ${dayItem.day || idx + 1} Afternoon`, text: dayItem.afternoon, start: "130000", end: "170000" },
      { name: "Evening", summary: `${destination} - Day ${dayItem.day || idx + 1} Evening`, text: dayItem.evening, start: "180000", end: "210000" },
    ];

    blocks.forEach((b) => {
      if (!b.text || b.text === "Free time") return;
      const uid = `aetheria-${dateClean}-${b.start}-${idx}@aetheria.travel`;
      lines.push("BEGIN:VEVENT");
      lines.push(`UID:${uid}`);
      lines.push(`DTSTAMP:${nowIso}`);
      lines.push(`DTSTART:${dateClean}T${b.start}`);
      lines.push(`DTEND:${dateClean}T${b.end}`);
      lines.push(`SUMMARY:${escapeIcsText(b.summary)}`);
      lines.push(`DESCRIPTION:${escapeIcsText(b.text)}`);
      lines.push(`LOCATION:${escapeIcsText(destination)}`);
      lines.push("STATUS:CONFIRMED");
      lines.push("END:VEVENT");
    });
  });

  lines.push("END:VCALENDAR");

  const icsBody = lines.map(foldLine).join("\r\n") + "\r\n";
  const blob = new Blob([icsBody], { type: "text/calendar;charset=utf-8" });
  const url = URL.createObjectURL(blob);

  const a = document.createElement("a");
  a.href = url;
  a.download = `itinerary_${destination.toLowerCase().replace(/[^a-z0-9]/g, "_")}.ics`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
