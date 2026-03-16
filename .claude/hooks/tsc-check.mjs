import { readFileSync, mkdirSync, writeFileSync, existsSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import { execSync } from 'child_process';

const __dirname = dirname(fileURLToPath(import.meta.url));
const projectDir = process.env.CLAUDE_PROJECT_DIR || join(__dirname, '..', '..');
const homeDir = process.env.USERPROFILE || process.env.HOME || '';

try {
    const input = readFileSync(0, 'utf-8');
    const data = JSON.parse(input);

    const toolName = data.tool_name || '';
    const toolInput = data.tool_input || {};

    if (!['Write', 'Edit', 'MultiEdit'].includes(toolName)) process.exit(0);

    let filePaths = [];
    if (toolName === 'MultiEdit' && toolInput.edits) {
        filePaths = toolInput.edits.map(e => e.file_path).filter(Boolean);
    } else if (toolInput.file_path) {
        filePaths = [toolInput.file_path];
    }

    // Only check TS/JS files
    filePaths = filePaths.filter(f => /\.(ts|tsx|js|jsx)$/.test(f));
    if (filePaths.length === 0) process.exit(0);

    const sessionId = data.session_id || 'default';
    const cacheDir = join(homeDir, '.claude', 'tsc-cache', sessionId);
    mkdirSync(cacheDir, { recursive: true });

    // Detect repos from file paths
    const repos = new Set();
    for (const fp of filePaths) {
        const relative = fp.replace(projectDir.replace(/\\/g, '/'), '').replace(/^[/\\]/, '');
        const first = relative.split(/[/\\]/)[0];
        const known = ['frontend', 'client', 'web', 'app', 'ui', 'backend', 'server', 'api', 'src', 'services', 'database'];
        if (known.includes(first)) repos.add(first);
    }

    if (repos.size === 0) process.exit(0);

    let errorCount = 0;
    let errorOutput = '';
    const failedRepos = [];

    process.stderr.write(`⚡ TypeScript check on: ${[...repos].join(' ')}\n`);

    for (const repo of repos) {
        const repoPath = join(projectDir, repo);
        if (!existsSync(join(repoPath, 'tsconfig.json'))) continue;

        process.stderr.write(`  Checking ${repo}... `);

        let tscCmd = 'npx tsc --noEmit';
        if (existsSync(join(repoPath, 'tsconfig.app.json'))) {
            tscCmd = 'npx tsc --project tsconfig.app.json --noEmit';
        }

        try {
            execSync(tscCmd, { cwd: repoPath, stdio: 'pipe', timeout: 60000 });
            process.stderr.write('✅ OK\n');
        } catch (err) {
            const output = (err.stdout || '').toString() + (err.stderr || '').toString();
            process.stderr.write('❌ Errors found\n');
            errorCount++;
            failedRepos.push(repo);
            errorOutput += `\n=== Errors in ${repo} ===\n${output}`;
        }
    }

    if (errorCount > 0) {
        writeFileSync(join(cacheDir, 'last-errors.txt'), errorOutput);
        writeFileSync(join(cacheDir, 'affected-repos.txt'), failedRepos.join('\n'));

        const tsErrors = errorOutput.split('\n').filter(l => l.includes('error TS'));
        process.stderr.write(`\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n`);
        process.stderr.write(`🚨 TypeScript errors found in ${errorCount} repo(s): ${failedRepos.join(' ')}\n`);
        process.stderr.write(`━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n`);
        process.stderr.write(`👉 IMPORTANT: Use the auto-error-resolver agent to fix the errors\n\n`);
        process.stderr.write(`Error Preview:\n`);
        tsErrors.slice(0, 10).forEach(l => process.stderr.write(l + '\n'));
        if (tsErrors.length > 10) process.stderr.write(`... and ${tsErrors.length - 10} more errors\n`);
        process.exit(1);
    }

    process.exit(0);
} catch (err) {
    process.exit(0);
}
