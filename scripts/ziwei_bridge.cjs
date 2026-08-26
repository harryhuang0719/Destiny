"use strict";

// Static bridge between Python and iztro. Input arrives as JSON on stdin so
// birth data can never become executable JavaScript source.
const fs = require("node:fs");
const { astro } = require("iztro");

function fail(message) {
  process.stderr.write(`${message}\n`);
  process.exit(1);
}

let input;
try {
  input = JSON.parse(fs.readFileSync(0, "utf8"));
} catch (error) {
  fail(`Invalid JSON input: ${error.message}`);
}

const { solarDate, hourIndex, gender } = input;
if (!/^\d{4}-\d{2}-\d{2}$/.test(solarDate)) fail("Invalid solarDate");
if (!Number.isInteger(hourIndex) || hourIndex < 0 || hourIndex > 12) {
  fail("Invalid hourIndex");
}
if (gender !== "男" && gender !== "女") fail("Invalid gender");

try {
  const result = astro.bySolar(solarDate, hourIndex, gender, true, "zh-CN");
  const output = {
    soul: result.soul,
    body: result.body,
    fiveElementsClass: result.fiveElementsClass,
    gender: result.gender,
    earthlyBranchOfSoulPalace: result.earthlyBranchOfSoulPalace,
    earthlyBranchOfBodyPalace: result.earthlyBranchOfBodyPalace,
    palaces: (result.palaces || []).map((palace) => ({
      name: palace.name,
      heavenlyStem: palace.heavenlyStem,
      earthlyBranch: palace.earthlyBranch,
      majorStars: (palace.majorStars || []).map((star) => ({
        name: star.name,
        type: star.type,
        brightness: star.brightness || "",
        mutagen: star.mutagen || "",
      })),
      minorStars: (palace.minorStars || []).map((star) => ({
        name: star.name,
        type: star.type,
        brightness: star.brightness || "",
        mutagen: star.mutagen || "",
      })),
      adjectiveStars: (palace.adjectiveStars || []).map((star) => ({
        name: star.name,
      })),
      ages: palace.ages,
      decadal: palace.decadal
        ? {
            range: palace.decadal.range,
            heavenlyStem: palace.decadal.heavenlyStem,
            earthlyBranch: palace.decadal.earthlyBranch,
          }
        : null,
      isEmpty:
        typeof palace.isEmpty === "function"
          ? Boolean(palace.isEmpty())
          : Boolean(palace.isEmpty),
    })),
  };
  process.stdout.write(JSON.stringify(output));
} catch (error) {
  fail(`iztro error: ${error.message}`);
}
