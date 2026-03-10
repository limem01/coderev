import * as path from 'path';
import Mocha from 'mocha';
import { glob } from 'vscode-test';

export function run(): Promise<void> {
    const mocha = new Mocha({ ui: 'tdd', color: true });
    const testsRoot = path.resolve(__dirname, '.');

    return new Promise((resolve, reject) => {
        // Use simple file finding instead of glob for reliability
        const fs = require('fs');
        const files = fs.readdirSync(testsRoot)
            .filter((f: string) => f.endsWith('.test.js'));

        files.forEach((f: string) => mocha.addFile(path.resolve(testsRoot, f)));

        try {
            mocha.run((failures: number) => {
                if (failures > 0) {
                    reject(new Error(`${failures} tests failed.`));
                } else {
                    resolve();
                }
            });
        } catch (err) {
            reject(err);
        }
    });
}
