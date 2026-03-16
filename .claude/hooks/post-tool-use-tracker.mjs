import { readFileSync, mkdirSync, appendFileSync, writeFileSync, existsSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const projectDir = process.env.CLAUDE_PROJECT_DIR || join(__dirname, '..', '..');

try {
    const input = readFileSync(0, 'utf-8');
    const data = JSON.parse(input);

    const toolName = data.tool_name || '';
    const filePath = (data.tool_input && data.tool_input.file_path) || '';
    const sessionId = data.session_id || 'default';

    if (!['Edit', 'MultiEdit', 'Write'].includes(toolName) || !filePath) process.exit(0);
    if (/\.(md|markdown)$/.test(filePath)) process.exit(0);

    const cacheDir = join(projectDir, '.claude', 'tsc-cache', sessionId);
    mkdirSync(cacheDir, { recursive: true });

    const relative = filePath.replace(projectDir.replace(/\\/g, '/'), '').replace(/^[/\\]/, '');
    const parts = relative.split(/[/\\]/);
    const repo = parts[0] || 'root';

    const known = ['frontend', 'client', 'web', 'app', 'ui', 'backend', 'server', 'api', 'src', 'services', 'database', 'prisma', 'migrations', 'packages', 'examples'];
    if (!known.includes(repo) && parts.length <= 1) process.exit(0);
    if (!known.includes(repo)) process.exit(0);

    appendFileSync(join(cacheDir, 'edited-files.log'), `${Date.now()}:${filePath}:${repo}\n`);

    const reposFile = join(cacheDir, 'affected-repos.txt');
    const existing = existsSync(reposFile) ? readFileSync(reposFile, 'utf-8') : '';
    if (!existing.split('\n').includes(repo)) {
        appendFileSync(reposFile, repo + '\n');
    }

    process.exit(0);
} catch (err) {
    process.exit(0);
}
