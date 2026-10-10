// Every sport the API can send (tools/sports.py), with its name in both languages and the icon group it is drawn
// with (components/plan/SportIcon.tsx). A code that is not here (a sport Garmin adds later) still works: its name is
// the code in words and it gets the icon of the "other" group.

export type SportGroup =
  | "run" | "ride" | "swim" | "walk" | "hike" | "strength" | "cardio" | "mind" | "row" | "climb" | "snow" | "skate"
  | "paddle" | "water" | "dive" | "racket" | "team" | "golf" | "combat" | "multisport" | "motor" | "air" | "outdoor"
  | "wheelchair" | "rest" | "other";

type Sport = { group: SportGroup; nl: string; en: string };

const s = (group: SportGroup, nl: string, en: string): Sport => ({ group, nl, en });

export const SPORTS: Record<string, Sport> = {
  all: s("other", "Alle sporten", "All sports"),
  rest: s("rest", "Rust", "Rest"),
  other: s("other", "Overig", "Other"),

  run: s("run", "Hardlopen", "Running"),
  ride: s("ride", "Fietsen", "Cycling"),
  e_bike: s("ride", "E-bike", "E-bike"),
  hand_cycling: s("ride", "Handbiken", "Hand cycling"),
  swim: s("swim", "Zwemmen", "Swimming"),
  multi_sport: s("multisport", "Multisport", "Multisport"),
  transition: s("multisport", "Wissel", "Transition"),

  walking: s("walk", "Wandelen", "Walking"),
  hiking: s("hike", "Hiken", "Hiking"),
  rucking: s("hike", "Rucking", "Rucking"),
  mountaineering: s("climb", "Bergbeklimmen", "Mountaineering"),
  steps: s("walk", "Stappen", "Steps"),

  strength_training: s("strength", "Kracht", "Strength"),
  fitness_equipment: s("strength", "Fitness", "Fitness"),
  indoor_cardio: s("cardio", "Cardio", "Cardio"),
  hiit: s("cardio", "HIIT", "HIIT"),
  elliptical: s("cardio", "Crosstrainer", "Elliptical"),
  stair_climbing: s("cardio", "Traplopen", "Stair climbing"),
  floor_climbing: s("cardio", "Trappen lopen", "Floor climbing"),
  jump_rope: s("cardio", "Touwtjespringen", "Jump rope"),
  dance: s("cardio", "Dansen", "Dance"),
  indoor_rowing: s("row", "Indoor roeien", "Indoor rowing"),
  rowing: s("row", "Roeien", "Rowing"),
  yoga: s("mind", "Yoga", "Yoga"),
  pilates: s("mind", "Pilates", "Pilates"),
  mobility: s("mind", "Mobiliteit", "Mobility"),
  breathwork: s("mind", "Ademwerk", "Breathwork"),
  meditation: s("mind", "Meditatie", "Meditation"),

  rock_climbing: s("climb", "Klimmen", "Rock climbing"),
  indoor_climbing: s("climb", "Indoor klimmen", "Indoor climbing"),
  bouldering: s("climb", "Boulderen", "Bouldering"),

  winter_sports: s("snow", "Wintersport", "Winter sports"),
  resort_skiing: s("snow", "Skiën", "Skiing"),
  resort_snowboarding: s("snow", "Snowboarden", "Snowboarding"),
  backcountry_skiing: s("snow", "Toerskiën", "Backcountry skiing"),
  backcountry_snowboarding: s("snow", "Splitboarden", "Backcountry snowboarding"),
  cross_country_skiing: s("snow", "Langlaufen", "Cross-country skiing"),
  skate_skiing: s("snow", "Skaten (langlauf)", "Skate skiing"),
  snow_shoe: s("snow", "Sneeuwschoenwandelen", "Snowshoeing"),
  snowmobiling: s("motor", "Sneeuwscooter", "Snowmobiling"),
  skating: s("skate", "Schaatsen", "Ice skating"),
  inline_skating: s("skate", "Inline skaten", "Inline skating"),
  skateboarding: s("skate", "Skateboarden", "Skateboarding"),

  water_sports: s("water", "Watersport", "Water sports"),
  kayaking: s("paddle", "Kajakken", "Kayaking"),
  paddling: s("paddle", "Peddelen", "Paddling"),
  stand_up_paddleboarding: s("paddle", "Suppen", "Stand-up paddleboarding"),
  whitewater_rafting: s("paddle", "Wildwatervaren", "Whitewater rafting"),
  boating: s("paddle", "Varen", "Boating"),
  sailing: s("water", "Zeilen", "Sailing"),
  surfing: s("water", "Surfen", "Surfing"),
  windsurfing: s("water", "Windsurfen", "Windsurfing"),
  kiteboarding: s("water", "Kitesurfen", "Kiteboarding"),
  wind_kite_surfing: s("water", "Wind- en kitesurfen", "Wind and kite surfing"),
  wakeboarding: s("water", "Wakeboarden", "Wakeboarding"),
  wakesurfing: s("water", "Wakesurfen", "Wakesurfing"),
  waterskiing: s("water", "Waterskiën", "Waterskiing"),
  water_tubing: s("water", "Tuben", "Water tubing"),
  offshore_grinding: s("water", "Grinden (zeilen)", "Offshore grinding"),
  onshore_grinding: s("strength", "Grinden (op de wal)", "Onshore grinding"),
  snorkeling: s("dive", "Snorkelen", "Snorkelling"),
  diving: s("dive", "Duiken", "Diving"),
  single_gas_diving: s("dive", "Duiken", "Diving"),
  multi_gas_diving: s("dive", "Duiken (meerdere gassen)", "Multi-gas diving"),
  gauge_diving: s("dive", "Duiken (gauge)", "Gauge diving"),
  ccr_diving: s("dive", "Duiken (rebreather)", "CCR diving"),
  apnea_diving: s("dive", "Apneu", "Apnea diving"),
  pool_apnea: s("dive", "Apneu in het zwembad", "Pool apnea"),
  apnea_hunting: s("dive", "Speervissen", "Apnea hunting"),

  racket_sports: s("racket", "Racketsport", "Racket sports"),
  tennis: s("racket", "Tennis", "Tennis"),
  padel: s("racket", "Padel", "Padel"),
  pickleball: s("racket", "Pickleball", "Pickleball"),
  badminton: s("racket", "Badminton", "Badminton"),
  squash: s("racket", "Squash", "Squash"),
  table_tennis: s("racket", "Tafeltennis", "Table tennis"),
  platform_tennis: s("racket", "Platformtennis", "Platform tennis"),
  racquetball: s("racket", "Racquetball", "Racquetball"),

  team_sports: s("team", "Teamsport", "Team sports"),
  soccer: s("team", "Voetbal", "Football"),
  basketball: s("team", "Basketbal", "Basketball"),
  volleyball: s("team", "Volleybal", "Volleyball"),
  rugby: s("team", "Rugby", "Rugby"),
  american_football: s("team", "American football", "American football"),
  baseball: s("team", "Honkbal", "Baseball"),
  softball: s("team", "Softbal", "Softball"),
  cricket: s("team", "Cricket", "Cricket"),
  ice_hockey: s("team", "IJshockey", "Ice hockey"),
  field_hockey: s("team", "Hockey", "Field hockey"),
  lacrosse: s("team", "Lacrosse", "Lacrosse"),
  ultimate_disc: s("team", "Ultimate frisbee", "Ultimate"),

  golf: s("golf", "Golf", "Golf"),
  disc_golf: s("golf", "Discgolf", "Disc golf"),
  boxing: s("combat", "Boksen", "Boxing"),
  mixed_martial_arts: s("combat", "MMA", "Mixed martial arts"),
  archery: s("outdoor", "Boogschieten", "Archery"),
  hunting: s("outdoor", "Jagen", "Hunting"),
  fishing: s("outdoor", "Vissen", "Fishing"),
  hunting_fishing: s("outdoor", "Jagen en vissen", "Hunting and fishing"),
  horseback_riding: s("outdoor", "Paardrijden", "Horseback riding"),
  overland: s("motor", "Overlanding", "Overlanding"),

  driving_general: s("motor", "Autorijden", "Driving"),
  auto_racing: s("motor", "Autosport", "Auto racing"),
  motorcycling: s("motor", "Motorrijden", "Motorcycling"),
  motocross: s("motor", "Motocross", "Motocross"),
  atv: s("motor", "Quad", "ATV"),
  flying: s("air", "Vliegen", "Flying"),
  hang_gliding: s("air", "Deltavliegen", "Hang gliding"),
  sky_diving: s("air", "Parachutespringen", "Skydiving"),
  wingsuit_flying: s("air", "Wingsuitvliegen", "Wingsuit flying"),
  rc_drone: s("air", "Drone", "RC drone"),

  para_sports: s("wheelchair", "Parasport", "Para sports"),
  wheelchair_push_run: s("wheelchair", "Rolstoel (hardlopen)", "Wheelchair push run"),
  wheelchair_push_walk: s("wheelchair", "Rolstoel (wandelen)", "Wheelchair push walk"),

  e_sport: s("other", "E-sport", "E-sports"),
  stop_watch: s("other", "Stopwatch", "Stopwatch"),
  safety: s("other", "Veiligheid", "Safety"),
  assistance: s("other", "Hulpverzoek", "Assistance"),
  incident_detected: s("other", "Incident", "Incident detected"),
};

/** Name of a sport in a language; an unknown code in words ("cargo_biking" -> "cargo biking"). */
export function sportName(code: string, lang: "nl" | "en"): string {
  return SPORTS[code]?.[lang] ?? code.replace(/_/g, " ");
}

/** How effort reads for a sport: pace per km (on foot), per 100 m (swimming), per 500 m (rowing) or speed. */
export type Effort = "pace" | "swim" | "row" | "speed";

export function effortKind(code: string): Effort {
  const g = sportGroup(code);
  if (g === "run" || g === "walk" || g === "hike" || g === "wheelchair") return "pace";
  if (g === "swim" || g === "row") return g;
  return "speed";
}

/** A name inside a sentence: lower case, abbreviations stay (HIIT, MMA). */
export function lowerName(name: string): string {
  return name.split(" ").map((w) => (w.length > 1 && w === w.toUpperCase() ? w : w.toLowerCase())).join(" ");
}

export function sportGroup(code: string): SportGroup {
  return SPORTS[code]?.group ?? "other";
}
