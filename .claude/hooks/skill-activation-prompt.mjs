import { readFileSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));

try {
    const input = readFileSync(0, 'utf-8');
    const data = JSON.parse(input);
    const prompt = data.prompt.toLowerCase();

    const rulesPath = join(__dirname, '..', 'skills', 'skill-rules.json');
    const rules = JSON.parse(readFileSync(rulesPath, 'utf-8'));

    const matchedSkills = [];

    for (const [skillName, config] of Object.entries(rules.skills)) {
        const triggers = config.promptTriggers;
        if (!triggers) continue;

        if (triggers.keywords) {
            const keywordMatch = triggers.keywords.some(kw => prompt.includes(kw.toLowerCase()));
            if (keywordMatch) {
                matchedSkills.push({ name: skillName, matchType: 'keyword', config });
                continue;
            }
        }

        if (triggers.intentPatterns) {
            const intentMatch = triggers.intentPatterns.some(pattern => {
                return new RegExp(pattern, 'i').test(prompt);
            });
            if (intentMatch) {
                matchedSkills.push({ name: skillName, matchType: 'intent', config });
            }
        }
    }

    if (matchedSkills.length > 0) {
        let output = '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n';
        output += '🎯 SKILL ACTIVATION CHECK\n';
        output += '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n';

        const groups = { critical: '⚠️ CRITICAL SKILLS (REQUIRED)', high: '📚 RECOMMENDED SKILLS', medium: '💡 SUGGESTED SKILLS', low: '📌 OPTIONAL SKILLS' };
        for (const [priority, label] of Object.entries(groups)) {
            const skills = matchedSkills.filter(s => s.config.priority === priority);
            if (skills.length > 0) {
                output += `${label}:\n`;
                skills.forEach(s => output += `  → ${s.name}\n`);
                output += '\n';
            }
        }

        output += 'ACTION: Use Skill tool BEFORE responding\n';
        output += '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n';
        console.log(output);
    }

    process.exit(0);
} catch (err) {
    console.error('Error in skill-activation-prompt hook:', err);
    process.exit(1);
}
