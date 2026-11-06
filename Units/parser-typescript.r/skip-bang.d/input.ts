/* Taken from #4384 submitted by @naktinis */
class SomeClass {
  brokenMethod() {
    const x = {a: !true ? 1 : 2};
  }

  missingMethod() {}
}
