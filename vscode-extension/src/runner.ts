import * as vscode from 'vscode';
import { execFile } from 'child_process';
import * as path from 'path';
import * as fs from 'fs';
import * as os from 'os';

export interface ReviewIssue {
    line: number;
    endLine?: number;
    severity: 'critical' | 'high' | 'medium' | 'low';
    category: string;
    message: string;
    suggestion?: string;
}

export interface ReviewResult {
    file: string;
    issues: ReviewIssue[];
    summary?: string;
}

export interface CostEstimate {
    model: string;
    inputTokens: string;
    outputTokens: string;
    totalCost: string;
}

export class CodeRevRunner {
    private cliPath: string;
    private defaultFocus: string[];
    private severityFilter: string;

    constructor(config: vscode.WorkspaceConfiguration) {
        this.cliPath = config.get<string>('cliPath') ?? 'coderev';
        this.defaultFocus = config.get<string[]>('defaultFocus') ?? [];
        this.severityFilter = config.get<string>('severityFilter') ?? 'all';
    }

    updateConfig(config: vscode.WorkspaceConfiguration): void {
        this.cliPath = config.get<string>('cliPath') ?? 'coderev';
        this.defaultFocus = config.get<string[]>('defaultFocus') ?? [];
        this.severityFilter = config.get<string>('severityFilter') ?? 'all';
    }

    async reviewFile(
        filePath: string,
        cancellation?: vscode.CancellationToken
    ): Promise<ReviewResult> {
        const args = ['review', filePath, '--format', 'json'];
        this.appendFocusArgs(args);

        const output = await this.run(args, path.dirname(filePath), cancellation);
        return this.parseReviewOutput(filePath, output);
    }

    async reviewSelection(
        filePath: string,
        text: string,
        startLine: number,
        cancellation?: vscode.CancellationToken
    ): Promise<ReviewResult> {
        // Write selection to a temp file and review it
        const ext = path.extname(filePath);
        const tmpFile = path.join(os.tmpdir(), `coderev-selection${ext}`);

        try {
            fs.writeFileSync(tmpFile, text, 'utf-8');
            const args = ['review', tmpFile, '--format', 'json'];
            this.appendFocusArgs(args);

            const output = await this.run(args, path.dirname(filePath), cancellation);
            const result = this.parseReviewOutput(filePath, output);

            // Adjust line numbers to match original file
            for (const issue of result.issues) {
                issue.line = issue.line + startLine - 1;
                if (issue.endLine !== undefined) {
                    issue.endLine = issue.endLine + startLine - 1;
                }
            }

            return result;
        } finally {
            try {
                fs.unlinkSync(tmpFile);
            } catch {
                // Ignore cleanup errors
            }
        }
    }

    async reviewDiff(
        cwd: string,
        staged: boolean,
        cancellation?: vscode.CancellationToken
    ): Promise<ReviewResult> {
        const args = ['diff'];
        if (staged) {
            args.push('--staged');
        }
        args.push('--format', 'json');
        this.appendFocusArgs(args);

        const output = await this.run(args, cwd, cancellation);
        return this.parseReviewOutput('diff', output);
    }

    async estimateCost(filePath: string): Promise<CostEstimate> {
        const args = ['review', filePath, '--estimate', '--format', 'json'];
        const output = await this.run(args, path.dirname(filePath));

        try {
            const data = JSON.parse(output);
            return {
                model: data.model ?? 'unknown',
                inputTokens: data.input_tokens?.toLocaleString() ?? '?',
                outputTokens: data.estimated_output_tokens?.toLocaleString() ?? '?',
                totalCost: data.total_cost_formatted ?? data.total_cost_usd ?? '?',
            };
        } catch {
            return {
                model: 'unknown',
                inputTokens: '?',
                outputTokens: '?',
                totalCost: output.trim(),
            };
        }
    }

    private appendFocusArgs(args: string[]): void {
        for (const focus of this.defaultFocus) {
            args.push('--focus', focus);
        }
    }

    private run(
        args: string[],
        cwd: string,
        cancellation?: vscode.CancellationToken
    ): Promise<string> {
        return new Promise((resolve, reject) => {
            const proc = execFile(
                this.cliPath,
                args,
                {
                    cwd,
                    timeout: 120_000,
                    maxBuffer: 10 * 1024 * 1024,
                    env: { ...process.env },
                },
                (error, stdout, stderr) => {
                    if (error) {
                        // Exit code 1 with JSON output means issues found (not an error)
                        if (error.code === 1 && stdout.trim().startsWith('{')) {
                            resolve(stdout);
                            return;
                        }
                        reject(new Error(stderr || error.message));
                        return;
                    }
                    resolve(stdout);
                }
            );

            cancellation?.onCancellationRequested(() => {
                proc.kill();
                reject(new Error('Review cancelled.'));
            });
        });
    }

    private parseReviewOutput(filePath: string, output: string): ReviewResult {
        try {
            const data = JSON.parse(output);

            // Handle both single-file and multi-file JSON output
            const fileData = data[filePath] ?? data[Object.keys(data)[0]] ?? data;
            const rawIssues: any[] = fileData.issues ?? data.issues ?? [];

            const issues: ReviewIssue[] = rawIssues
                .map((issue: any) => ({
                    line: issue.line ?? 1,
                    endLine: issue.end_line ?? issue.endLine,
                    severity: normalizeSeverity(issue.severity),
                    category: issue.category ?? 'general',
                    message: issue.message ?? issue.description ?? '',
                    suggestion: issue.suggestion ?? issue.fix,
                }))
                .filter((issue: ReviewIssue) => this.passesSeverityFilter(issue.severity));

            return {
                file: filePath,
                issues,
                summary: fileData.summary ?? data.summary,
            };
        } catch {
            // If JSON parsing fails, try to extract useful info from raw output
            return {
                file: filePath,
                issues: [],
                summary: output.trim() || undefined,
            };
        }
    }

    private passesSeverityFilter(severity: string): boolean {
        if (this.severityFilter === 'all') {
            return true;
        }
        const order = ['low', 'medium', 'high', 'critical'];
        const minIdx = order.indexOf(this.severityFilter);
        const issueIdx = order.indexOf(severity);
        return issueIdx >= minIdx;
    }
}

function normalizeSeverity(s: any): ReviewIssue['severity'] {
    const str = String(s).toLowerCase();
    if (str === 'critical') { return 'critical'; }
    if (str === 'high') { return 'high'; }
    if (str === 'medium') { return 'medium'; }
    return 'low';
}
