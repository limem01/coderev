import * as vscode from 'vscode';
import { ReviewResult } from './runner';

export class ReviewOutputPanel {
    private channel: vscode.OutputChannel;

    constructor() {
        this.channel = vscode.window.createOutputChannel('CodeRev');
    }

    showReview(label: string, result: ReviewResult): void {
        this.channel.clear();
        this.channel.appendLine(`CodeRev Review: ${label}`);
        this.channel.appendLine('='.repeat(60));
        this.channel.appendLine('');

        if (result.summary) {
            this.channel.appendLine(`Summary: ${result.summary}`);
            this.channel.appendLine('');
        }

        if (result.issues.length === 0) {
            this.channel.appendLine('No issues found.');
            this.channel.show(true);
            return;
        }

        this.channel.appendLine(`Found ${result.issues.length} issue(s):`);
        this.channel.appendLine('');

        const grouped = groupBy(result.issues, (i) => i.severity);
        const severityOrder = ['critical', 'high', 'medium', 'low'] as const;

        for (const severity of severityOrder) {
            const issues = grouped[severity];
            if (!issues || issues.length === 0) {
                continue;
            }

            const icon = severityIcon(severity);
            this.channel.appendLine(`${icon} ${severity.toUpperCase()} (${issues.length})`);
            this.channel.appendLine('-'.repeat(40));

            for (const issue of issues) {
                const loc = issue.endLine && issue.endLine !== issue.line
                    ? `L${issue.line}-${issue.endLine}`
                    : `L${issue.line}`;

                this.channel.appendLine(`  [${loc}] [${issue.category}] ${issue.message}`);
                if (issue.suggestion) {
                    this.channel.appendLine(`    -> ${issue.suggestion}`);
                }
            }

            this.channel.appendLine('');
        }

        this.channel.show(true);
    }
}

function severityIcon(severity: string): string {
    switch (severity) {
        case 'critical': return '\u{1F6D1}';
        case 'high': return '\u{1F534}';
        case 'medium': return '\u{1F7E1}';
        case 'low': return '\u{1F535}';
        default: return '\u{2139}\u{FE0F}';
    }
}

function groupBy<T>(items: T[], key: (item: T) => string): Record<string, T[]> {
    const result: Record<string, T[]> = {};
    for (const item of items) {
        const k = key(item);
        (result[k] ??= []).push(item);
    }
    return result;
}
