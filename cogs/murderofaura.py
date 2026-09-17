/**
 * Murder Mystery Game Commands
 * ----------------------------
 * Requires: discord.js v14
 *   npm install discord.js
 *
 * Commands:
 *   !files          -> shows the suspect list + statements
 *   !accuse <name>  -> guess the culprit
 *
 * Drop this into your existing bot's messageCreate handler,
 * or use it as a standalone bot (fill in your TOKEN below).
 */

const { Client, GatewayIntentBits, EmbedBuilder } = require('discord.js');

// ---------------------------------------------------------------------------
// 1. YOUR CASE DATA — edit this to match your actual mystery
// ---------------------------------------------------------------------------
const suspects = [
  {
    name: 'Soul',
    statement: 'I think the killer has to be in the Spell Book Group. It had to be witchery.',
    condition: 'This statement is true if Eden won 3 competitions this season.',
    correct: false,
  },
  {
    name: 'Release',
    statement: "I don't think Tyler did it. He was in the Audio Room at the time.",
    condition: 'This statement is true if there was an even amount of people that won a competition this season.',
    correct: false,
  },
  {
    name: 'Tyler',
    statement: "I don't think anyone who bit the apple and made jury did this.",
    condition: 'This statement is false if Omega lost an HOH competition.',
    correct: false,
  },
  {
    name: 'Aaronic',
    statement: "I think as much Emerald cheated, I don't think she had enough time to do this.",
    condition: "This statement is true if Flair's statement is false.",
    correct: false,
  },
  {
    name: 'Ari',
    statement: "Flair was busy hanging out with Production during Aura's murder.",
    condition: 'This statement is true if the Snake won a temptation competition.',
    correct: true, // <- the killer
  },
  {
    name: 'Krevus',
    statement: 'I think the killer is trying to pull a fast one on us. I think the killer told the truth during their statement.',
    condition: 'This statement is false if the Urn Group member(s) lied during their statement(s).',
    correct: false,
  },
  {
    name: 'Omega',
    statement: "Obviously it wasn't me. I was too busy taking care of Benny to bother with Aura.",
    condition: 'This statement is true if both double evictions had someone that 0 votes to save.',
    correct: false,
  },
  {
    name: 'Goof',
    statement: "I think it's someone from the Urn Group. They probably hid the ashes of Aura in there.",
    condition: "This statement is true if Omega won his 5th competition before Krevus won his 2nd.",
    correct: false,
  },
  {
    name: 'Sixx',
    statement: 'I think Soul and Release are innocent. I mean they were barely here in the first place.',
    condition: 'This statement is true if there were 12 emotions in the Perceptive Potions competition.',
    correct: false,
  },
  {
    name: 'Hazel',
    statement: "I think it's someone skilled enough meaning it's someone who won a competition this season.",
    condition: 'This statement is true if every non He/Him cast member told the truth in their statement.',
    correct: false,
  },
  {
    name: 'Emerald',
    statement: "I think it's someone that won the Veto.",
    condition: 'This is false if the most votes to evict someone for one eviction night was 11.',
    correct: false,
  },
  {
    name: 'Flair',
    statement: "I don't think it's someone who got eliminated in a double eviction. I mean they can clear each other.",
    condition: 'This statement is true if 4 power weeks (someone wins HOH and veto) happened so far.',
    correct: false,
  },
];

// ---------------------------------------------------------------------------
// 2. Per-player game state
//    key:   userId
//    value: { attempts: number, startedAt: timestamp, solved: boolean }
// ---------------------------------------------------------------------------
const playerState = new Map();

function getState(userId) {
  if (!playerState.has(userId)) {
    playerState.set(userId, { attempts: 0, startedAt: null, solved: false });
  }
  return playerState.get(userId);
}

function formatDuration(ms) {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return minutes > 0 ? `${minutes}m ${seconds}s` : `${seconds}s`;
}

// ---------------------------------------------------------------------------
// 3. Command handlers
// ---------------------------------------------------------------------------
function handleFiles(message) {
  const state = getState(message.author.id);

  // Start the clock the first time they open the files (only if not already solved)
  if (!state.solved && state.startedAt === null) {
    state.startedAt = Date.now();
  }

  const embed = new EmbedBuilder()
    .setTitle('🗂️ Case Files — Suspect Statements')
    .setColor(0x8b0000)
    .setDescription(
      suspects
        .map(
          (s, i) =>
            `**${i + 1}. ${s.name}**\n> ${s.statement}\n> **${s.condition}**`
        )
        .join('\n\n')
    )
    .setFooter({ text: 'Use !accuse <suspect name> to make your guess.' });

  message.reply({ embeds: [embed] });
}

function handleAccuse(message, args) {
  const state = getState(message.author.id);

  if (state.solved) {
    return message.reply('You already solved this case! Use `!files` to review it, or start a new case.');
  }

  const guessName = args.join(' ').trim();
  if (!guessName) {
    return message.reply('You need to name a suspect. Example: `!accuse Suspect B`');
  }

  const match = suspects.find(
    (s) => s.name.toLowerCase() === guessName.toLowerCase()
  );

  if (!match) {
    return message.reply(
      `I don't recognize "${guessName}" as a suspect. Check \`!files\` for the exact names.`
    );
  }

  // Make sure the clock is running even if they !accuse without !files first
  if (state.startedAt === null) {
    state.startedAt = Date.now();
  }

  state.attempts += 1;

  if (!match.correct) {
    return message.reply(
      `❌ Incorrect guess! **${match.name}** wasn't the one. Try again. (Attempt #${state.attempts})`
    );
  }

  // Correct guess — stop the clock
  state.solved = true;
  const elapsed = Date.now() - state.startedAt;

  return message.reply(
    `✅ Correct! **${match.name}** did it.\n` +
      `It took you **${state.attempts}** accusation${state.attempts === 1 ? '' : 's'} ` +
      `and **${formatDuration(elapsed)}** to solve the case.`
  );
}

// ---------------------------------------------------------------------------
// 4. Standalone bot wiring (skip this section if you're merging into
//    an existing bot — just reuse handleFiles / handleAccuse there)
// ---------------------------------------------------------------------------
const PREFIX = '!';

const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.MessageContent,
  ],
});

client.on('messageCreate', (message) => {
  if (message.author.bot) return;
  if (!message.content.startsWith(PREFIX)) return;

  const args = message.content.slice(PREFIX.length).trim().split(/\s+/);
  const command = args.shift().toLowerCase();

  if (command === 'files') {
    handleFiles(message);
  } else if (command === 'accuse') {
    handleAccuse(message, args);
  }
});

client.once('ready', () => {
  console.log(`Logged in as ${client.user.tag}`);
});

// Replace with your bot token (or load from an env var / config file)
client.login(process.env.DISCORD_TOKEN);

module.exports = { suspects, playerState, handleFiles, handleAccuse };
