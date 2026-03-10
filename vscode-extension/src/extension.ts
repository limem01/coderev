import * as vscode from 'vscode';
import { CodeRevRunner } from './runner';
import { DiagnosticsManager } from './diagnostics';
import { ReviewOutputPanel } from './panel';

let runner: CodeRevRunner;
let diagnosticsManager: DiagnosticsManager;
let outputPanel: ReviewOutputPanel;

export function activate(context: vscode.ExtensionContext): void {
    const config = vscode.workspace.getConfiguration('coderev');
    runner = new CodeRevRunner(config);
    diagnosticsManager = new DiagnosticsManager();
    outputPanel = new ReviewOutputPanel();

    context.subscriptions.push(diagnosticsManager);

    // Review current file
    context.subscriptions.push(
        vscode.commands.registerCommand('coderev.reviewFile', async (uri?: vscode.Uri) => {
            const filePath = uri?.fsPath ?? vscode.window.activeTextEditor?.document.uri.fsPath;
            if (!filePath) {
                vscode.window.showWarningMessage('CodeRev: No file selected for review.');
                return;
            }
            await reviewFile(filePath);
        })
    );

    // Review selection
    context.subscriptions.push(
        vscode.commands.registerCommand('coderev.reviewSelection', async () => {
            const editor = vscode.window.activeTextEditor;
            if (!editor || editor.selection.isEmpty) {
                vscode.window.showWarningMessage('CodeRev: No text selected.');
                return;
            }
            const selectedText = editor.document.getText(editor.selection);
            const filePath = editor.document.uri.fsPath;
            const startLine = editor.selection.start.line + 1;
            await reviewSelection(filePath, selectedText, startLine);
        })
    );

    // Review git diff
    context.subscriptions.push(
        vscode.commands.registerCommand('coderev.reviewDiff', async () => {
            await reviewDiff(false);
        })
    );

    // Review staged changes
    context.subscriptions.push(
        vscode.commands.registerCommand('coderev.reviewStagedDiff', async () => {
            await reviewDiff(true);
        })
    );

    // Estimate cost
    context.subscriptions.push(
        vscode.commands.registerCommand('coderev.estimateCost', async () => {
            const filePath = vscode.window.activeTextEditor?.document.uri.fsPath;
            if (!filePath) {
                vscode.window.showWarningMessage('CodeRev: No file open to estimate.');
                return;
            }
            await estimateCost(filePath);
        })
    );

    // Auto-review on save
    if (config.get<boolean>('autoReviewOnSave')) {
        context.subscriptions.push(
            vscode.workspace.onDidSaveTextDocument(async (document) => {
                if (document.uri.scheme === 'file') {
                    await reviewFile(document.uri.fsPath, true);
                }
            })
        );
    }

    // Reload config on change
    context.subscriptions.push(
        vscode.workspace.onDidChangeConfiguration((e) => {
            if (e.affectsConfiguration('coderev')) {
                runner.updateConfig(vscode.workspace.getConfiguration('coderev'));
            }
        })
    );
}

async function reviewFile(filePath: string, silent: boolean = false): Promise<void> {
    await vscode.window.withProgress(
        {
            location: vscode.ProgressLocation.Notification,
            title: `CodeRev: Reviewing ${getFileName(filePath)}...`,
            cancellable: true,
        },
        async (_progress, token) => {
            try {
                const result = await runner.reviewFile(filePath, token);
                if (result.issues.length === 0) {
                    if (!silent) {
                        vscode.window.showInformationMessage('CodeRev: No issues found!');
                    }
                    diagnosticsManager.clear(vscode.Uri.file(filePath));
                    return;
                }

                diagnosticsManager.setIssues(vscode.Uri.file(filePath), result.issues);
                outputPanel.showReview(filePath, result);

                if (!silent) {
                    vscode.window.showInformationMessage(
                        `CodeRev: Found ${result.issues.length} issue(s) in ${getFileName(filePath)}.`
                    );
                }
            } catch (err) {
                handleError(err);
            }
        }
    );
}

async function reviewSelection(
    filePath: string,
    text: string,
    startLine: number
): Promise<void> {
    await vscode.window.withProgress(
        {
            location: vscode.ProgressLocation.Notification,
            title: 'CodeRev: Reviewing selection...',
            cancellable: true,
        },
        async (_progress, token) => {
            try {
                const result = await runner.reviewSelection(filePath, text, startLine, token);
                if (result.issues.length === 0) {
                    vscode.window.showInformationMessage('CodeRev: No issues found in selection!');
                    return;
                }

                diagnosticsManager.setIssues(vscode.Uri.file(filePath), result.issues);
                outputPanel.showReview(filePath, result);

                vscode.window.showInformationMessage(
                    `CodeRev: Found ${result.issues.length} issue(s) in selection.`
                );
            } catch (err) {
                handleError(err);
            }
        }
    );
}

async function reviewDiff(staged: boolean): Promise<void> {
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    if (!workspaceFolder) {
        vscode.window.showWarningMessage('CodeRev: No workspace folder open.');
        return;
    }

    const label = staged ? 'staged changes' : 'git diff';

    await vscode.window.withProgress(
        {
            location: vscode.ProgressLocation.Notification,
            title: `CodeRev: Reviewing ${label}...`,
            cancellable: true,
        },
        async (_progress, token) => {
            try {
                const result = await runner.reviewDiff(
                    workspaceFolder.uri.fsPath,
                    staged,
                    token
                );
                if (result.issues.length === 0) {
                    vscode.window.showInformationMessage(`CodeRev: No issues found in ${label}!`);
                    return;
                }

                outputPanel.showReview(label, result);

                vscode.window.showInformationMessage(
                    `CodeRev: Found ${result.issues.length} issue(s) in ${label}.`
                );
            } catch (err) {
                handleError(err);
            }
        }
    );
}

async function estimateCost(filePath: string): Promise<void> {
    try {
        const estimate = await runner.estimateCost(filePath);
        vscode.window.showInformationMessage(
            `CodeRev Cost Estimate: ~${estimate.totalCost} (${estimate.inputTokens} input tokens, model: ${estimate.model})`
        );
    } catch (err) {
        handleError(err);
    }
}

function handleError(err: unknown): void {
    const message = err instanceof Error ? err.message : String(err);
    if (message.includes('coderev: command not found') || message.includes('is not recognized')) {
        vscode.window.showErrorMessage(
            'CodeRev CLI not found. Install it with: pip install coderev',
            'Open Terminal'
        ).then((action) => {
            if (action === 'Open Terminal') {
                const terminal = vscode.window.createTerminal('CodeRev Install');
                terminal.show();
                terminal.sendText('pip install coderev');
            }
        });
    } else if (message.includes('rate limit') || message.includes('Rate Limit')) {
        vscode.window.showWarningMessage(`CodeRev: Rate limit hit. ${message}`);
    } else {
        vscode.window.showErrorMessage(`CodeRev: ${message}`);
    }
}

function getFileName(filePath: string): string {
    return filePath.split(/[/\\]/).pop() ?? filePath;
}

export function deactivate(): void {
    diagnosticsManager?.dispose();
}
