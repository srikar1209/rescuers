# Sim2Find demo film: full script (temporary)

**Target: about 3:55.** **Bold** means an action on screen. “Quotes” are spoken. *Italics* are captions. The Area 2 chat clue is accepted, so this recording applies four clues in total: the chat clue and three prepared demo clues.

## Scene 1: The wandering (0:00–0:15)

Shot: Night, dark street. Walter walks slowly in a thin shirt, no coat, looking around, confused. Close-ups of his feet, face, and breath in the cold air.

Caption: *Walter, 79 · 6:42 PM · 39°F*

Voiceover (calm, slow): “This is Walter. He’s 79, and he has dementia. A few minutes ago, he walked out of his care home. He doesn’t know he’s lost. He won’t call for help. And if someone shouts his name, he probably won’t answer.”

## Scene 2: The facts (0:15–0:25)

Shot: Walter disappears into the dark. Show the prepared typewriter slides, `typewriter_1` through `typewriter_3`, for about 2–3 seconds each. End on `typewriter_4_every_hour`.

Voiceover: “Every hour matters.”

## Scene 3: The search party (0:25–0:40)

Shot: Two searchers in coats with flashlights walk fast, stop at a corner, and look in different directions.

Searcher 1: “He left the care home at 6:30. Which way do we go?”

Searcher 2: “He could be anywhere. The woods, the streets, the fields...”

Voiceover: “Most searches start with a circle around the last place he was seen. But that’s a lot of ground, and it’s dark.”

## Scene 4: Starting the search (0:40–1:05)

Shot: Over the searchers’ shoulders, sim2find.us open on the Amherst map.

Searcher 1: “Let’s try Sim2Find. Walter left the care home at 6:30.”

**Click Autofill demo data.** Hold on the last-seen time and care-home pin. **Click Simulate.**

Voiceover: “Sim2Find starts with where and when Walter was last seen. Then it creates 5,000 possible walks across the Amherst terrain, including roads, buildings, woods, and streams, on a 10-meter grid.”

Caption: *5,000 simulated walks · Amherst terrain*

## Scene 5: How it works (1:05–1:30)

Shot: Heatmap appears. Slowly zoom toward the red, then show Search priorities.

Voiceover: “The walkers follow rules drawn from research on people with dementia. We tuned the model against 16 published lost-person statistics. The result is a heatmap, not a pin. Red shows where the modeled paths are most concentrated. The panel turns that into places to check first.”

Caption: *Research-based rules · calibrated to 16 statistics*

## Scene 6: Time matters (1:30–1:40)

**Click Location estimate.** **Drag the time slider earlier, then back to 21:00.**

Voiceover: “The estimate changes with time. Earlier, Walter may still be close. Later, he could be farther away.”

## Scene 7: The built-in chat and AI (1:40–2:15)

**Click Add a clue.** **Choose Area searched, no find.** **Type “I searched for Walter near Area 2 and did not find him.”** **Click Extract and continue.**

Voiceover: “We describe the search in plain words. The AI reads the report, and Sim2Find links Area 2 to the current map.”

**At the time question, enter 21:00 and click Continue.** **Pause on the final review.** **Open Model assumptions and show the estimated chance of detection.** **Click Accept and update map.** Hold on the changed heatmap; **click Focus estimate** if the map jumps to the searched area.

Voiceover: “The chat asks when it ended. We check the area and detection estimate, then accept. Now the map updates. A search with no find lowers priority without ruling the area out.”

Caption: *Area 2 searched · no find · reviewed by a person*

## Scene 8: A possible sighting (2:15–2:35)

**Click Case details.** **Click Add demo clue 1.** **Close Case details with ×.** Show the map update.

Voiceover: “A driver may have seen Walter at 6:45. Sim2Find checks which paths passed near that place and time. Those paths gain weight. The others remain possible because witnesses can be wrong.”

Caption: *Possible sighting · 6:45 PM*

## Scene 9: A camera saw nothing (2:35–2:50)

**Click Case details.** **Click Add demo clue 2.** **Close Case details with ×.** Show the update.

Voiceover: “An ATM camera saw no match. Paths that passed near it lose weight, but do not disappear. Cameras can miss people.”

Caption: *ATM camera · no match*

## Scene 10: Another area searched (2:50–3:10)

**Click Case details.** **Click Add demo clue 3.** **Close Case details with ×.** Show the update. **Click Focus estimate** if the view is centered on the clue pin.

Voiceover: “Searchers also checked the cemetery and found nothing. That area loses priority too. Each new clue changes where the team should look first.”

Caption: *Cemetery searched · nothing found*

## Scene 11: The reveal (3:10–3:25)

**Click Case details.** **Click Reveal fictional outcome.** Hold on the revealed spot.

Voiceover: “In this fictional case, Walter is in the wet woods behind a storage facility. The model never saw this answer. It worked from the terrain and the clues.”

Optional cut: Searchers’ flashlights find Walter, then cut back to the map.

## Scene 12: The proof and close (3:25–3:55)

Shot: Show `images/benchmark.png` full screen, then a black screen with *Sim2Find · sim2find.us*.

Voiceover: “One fictional demo is not proof. We also tested 999 synthetic cases based on published lost-person statistics. In the 954 cases with a sighting, Sim2Find beat circle search in 83% of cases that were not ties, and searched 56% less total ground. The decision stays with the search team. We help them choose where to look first.”

## Before recording

- Open sim2find.us early so the hosted service wakes before filming. Wait for the map to finish loading.
- The **Area 2** chat clue needs the current top areas, so keep the slider at **21:00** before opening chat. Enter the search completion time when prompted; the report itself does not provide one.
- If an AI key is configured, the video can show AI extraction. If it is unavailable, the chat still asks for missing details and can resolve the typed Area 2 locally; do not narrate that AI succeeded in that take.
- The accepted chat clue is **extra**. Add all three prepared demo clues afterward to unlock the fictional reveal. The resulting heatmap may differ from a run with only those three prepared clues.
- The benchmark is **synthetic**, not 999 real missing-person cases. The 83% figure is among sighting cases that were not ties. The 56% figure is the reduction in **total** area searched across those sighting cases.
- Record the voiceover separately and trim loading pauses. Export, upload as Unlisted to YouTube, and add the link to Devpost before your deadline.
