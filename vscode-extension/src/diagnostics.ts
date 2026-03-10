import * as vscode from 'vscode';
import { ReviewIssue } from './runner';

const SEVERITY_MAP: Record<ReviewIssue['severity'], vscode.DiagnosticSeverity> = {
    critical: vscode.DiagnosticSeverity.Error,
    high: vscode.DiagnosticSeverity.Error,
    medium: vscode.DiagnosticSeverity.Warning,
    low: vscode.DiagnosticSeverity.Information,
};

export class DiagnosticsManager implements vscode.Disposable {
    private collection: vscode.DiagnosticCollection;

    constructor() {
        this.collection = vscode.languages.createDiagnosticCollection('coderev');
    }

    setIssues(uri: vscode.Uri, issues: ReviewIssue[]): void {
        const diagnostics = issues.map((issue) => {
            const line = Math.max(0, issue.line - 1);
            const endLine = issue.endLine ? Math.max(0, issue.endLine - 1) : line;

            const range = new vscode.Range(
                new vscode.Position(line, 0),
                new vscode.Position(endLine, Number.MAX_SAFE_INTEGER)
            );

            const diagnostic = new vscode.Diagnostic(
                range,
                issue.message,
                SEVERITY_MAP[issue.severity]
            );

            diagnostic.source = 'CodeRev';
            diagnostic.code = issue.category;

            if (issue.suggestion) {
                diagnostic.relatedInformation = [
                    new vscode.DiagnosticRelatedInformation(
                        new vscode.Location(uri, range),
                        `Suggestion: ${issue.suggestion}`
                    ),
                ];
            }

            return diagnostic;
        });

        this.collection.set(uri, diagnostics);
    }

    clear(uri: vscode.Uri): void {
        this.collection.delete(uri);
    }

    dispose(): void {
        this.collection.dispose();
    }
}
